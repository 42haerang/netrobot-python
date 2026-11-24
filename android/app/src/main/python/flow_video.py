"""FLOW/WiFi UAV video-only UDP receiver, using documented wire-format facts.

Protocol references:
https://github.com/marshallrichards/turbodrone/blob/main/docs/research/wifi_uav.md
https://github.com/OpenIPC/decoder/blob/v2/docs/toys.md

Only video probes/fragment acknowledgements are sent. The flight-command area is empty.
"""
from collections import OrderedDict
import ipaddress
from pathlib import Path
import select
import socket
import struct
import threading
import time


def parse_fragment(packet):
    if len(packet)<56 or len(packet)>1080 or packet[:2]!=b'\x93\x01':
        return None
    if struct.unpack_from('<H',packet,2)[0]!=len(packet):return None
    sequence=struct.unpack_from('<Q',packet,8)[0]
    base=struct.unpack_from('<Q',packet,24)[0]
    index,total,length=struct.unpack_from('<III',packet,32)
    width,height=struct.unpack_from('<HH',packet,44)
    payload=packet[56:]
    if not sequence or not 1<=total<=1024 or index>=total or not 1<=length<=total*1024:
        return None
    need=min(1024,max(0,length-index*1024))
    if need<=0 or len(payload)<need or len(payload)>1024:return None
    if not 0<width<=4096 or not 0<height<=4096:return None
    return dict(sequence=sequence,base=base,index=index,total=total,length=length,width=width,height=height,quality=packet[48],payload=payload[:need])


class Frames:
    def __init__(self,header_loader,mode='zigzag'):
        self.load_header=header_loader
        self.mode=mode
        self.records=OrderedDict()
        self.newest=0
        self.last_delivered=0
        self.base=0
        self.last_packet=0.
        self.headers={}

    def add(self,packet,now=None):
        data=parse_fragment(packet)
        if data is None:return None
        now=time.monotonic() if now is None else now
        seq=data['sequence']
        if seq+64<self.newest:
            return None
        self.newest=max(self.newest,seq)
        self.last_packet=now
        if data['base']<seq:self.base=max(self.base,data['base'])
        if seq not in self.records:
            self.records[seq]={**data,'parts':{},'complete':False}
            self.records.move_to_end(seq)
            while len(self.records)>4:self.records.popitem(last=False)
        record=self.records[seq]
        if any(record[k]!=data[k] for k in ('total','length','width','height')):return None
        record['parts'][data['index']]=data['payload']
        if record['complete'] or len(record['parts'])!=record['total']:return None
        record['complete']=True
        if seq<=self.last_delivered:return None
        body=b''.join(record['parts'][i] for i in range(record['total']))[:record['length']]
        quality=record['quality'] if 1<=record['quality']<=100 else 50
        key=(quality,record['width'],record['height'],self.mode)
        if key not in self.headers:
            self.headers[key]=self.jpeg_header(*key)
            if len(self.headers)>16:self.headers.pop(next(iter(self.headers)))
        self.last_delivered=seq
        return self.headers[key]+body+(b'' if body.endswith(b'\xff\xd9') else b'\xff\xd9')

    def jpeg_header(self,quality,width,height,mode):
        header=bytearray(self.load_header(quality if mode=='zigzag' else 50))
        pos=2
        while pos+4<=len(header):
            marker=header[pos+1]
            length=int.from_bytes(header[pos+2:pos+4],'big')
            if marker==0xc0:
                header[pos+5:pos+9]=struct.pack('>HH',height,width)
            if marker==0xdb and mode=='raster':
                # JPEG DQT order is zig-zag. Some BL60x firmwares expect row-major tables.
                order=[]
                for diagonal in range(15):
                    coordinates=[(row,diagonal-row) for row in range(8) if 0<=diagonal-row<8]
                    if diagonal%2==0:coordinates.reverse()
                    order.extend(row*8+col for row,col in coordinates)
                at=pos+4
                while at<pos+2+length:
                    if header[at]>>4:raise ValueError('Only 8-bit JPEG quantization supported')
                    table=header[at+1:at+65]
                    raster=bytearray(64)
                    for value,index in zip(table,order):raster[index]=value
                    header[at+1:at+65]=raster
                    at+=65
            if marker==0xda:break
            pos+=2+length
        return bytes(header)

    def acknowledgement(self,now=None):
        now=time.monotonic() if now is None else now
        records=[]
        eligible=[(seq,r) for seq,r in self.records.items() if seq>self.base and self.newest-seq<5]
        for seq,r in eligible:
            if seq==self.newest and not r['complete'] and now-self.last_packet<.019:continue
            words=(r['total']+31)//32
            bitmap=[]
            for word in range(words):
                value=0
                for bit in range(32):
                    index=word*32+bit
                    if index>=r['total'] or index in r['parts']:value|=1<<bit
                bitmap.append(value)
            records.append(struct.pack('<QII',seq,1 if r['complete'] else 0,16+4*words)+struct.pack('<'+'I'*words,*bitmap))
        if eligible and all(r['complete'] for _,r in eligible) and now-self.last_packet>=.019:
            records.append(struct.pack('<QII',self.newest+1,3,16))
        header=bytearray(88)
        header[:8]=b'\xef\x02\0\0\x02\x02\0\x01'
        struct.pack_into('<I',header,8,len(records))
        # Offsets 12..81 remain zero: NO drone flight or stick command.
        header[82:86]=bytes.fromhex('324b142d')
        result=header+b''.join(records)
        struct.pack_into('<H',result,2,len(result))
        return bytes(result)


class Receiver:
    def __init__(self,header_loader):
        self.header_loader=header_loader
        self.lock=threading.Lock()
        self.jpeg=None
        self.sequence=0
        self.timestamp=0.
        self.error='드론 Wi-Fi에 연결한 뒤 영상 연결을 누르세요.'
        self.port=None
        self.stop_event=threading.Event()
        self.thread=None

    def connect(self,host='192.168.169.1',mode='zigzag'):
        address=ipaddress.ip_address(host)
        if address.version!=4 or not address.is_private or address.is_loopback:
            raise ValueError('드론의 사설 IPv4 주소를 입력하세요.')
        if mode not in ('zigzag','raster','q50'):raise ValueError('Unknown JPEG mode')
        self.close()
        self.stop_event=threading.Event()
        with self.lock:
            self.jpeg=None;self.sequence=0;self.timestamp=0.;self.port=None
            self.error=f'{host} 영상 응답 대기 · FLOW Wi-Fi 연결을 확인하세요.'
        self.thread=threading.Thread(target=self._run,args=(str(address),mode,self.stop_event),daemon=True)
        self.thread.start()

    def close(self):
        self.stop_event.set()
        if self.thread and self.thread.is_alive():self.thread.join(timeout=.4)

    def status(self):
        with self.lock:
            ready=self.jpeg is not None and time.monotonic()-self.timestamp<1.5
            return {'ready':ready,'sequence':self.sequence,'error':self.error,'port':self.port,'simulated':True}

    def frame(self):
        with self.lock:
            if self.jpeg is None or time.monotonic()-self.timestamp>1.5:return None,self.sequence
            return self.jpeg,self.sequence

    def _run(self,host,mode,stop):
        sockets={}
        active=None
        frames=Frames(self.header_loader,mode)
        last_probe={8800:0.,8801:0.}
        last_ack=0.
        suspicion=0
        try:
            for port in (8800,8801):
                sock=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
                sock.setsockopt(socket.SOL_SOCKET,socket.SO_RCVBUF,2*1024*1024)
                sock.bind(('0.0.0.0',0))
                sock.setblocking(False)
                sockets[sock]=port
            while not stop.is_set():
                now=time.monotonic()
                if active and now-frames.last_packet>3:
                    active=None;frames=Frames(self.header_loader,mode)
                    with self.lock:self.error='영상이 끊겼습니다. 드론 Wi-Fi를 확인하세요.'
                if active is None:
                    for sock,port in sockets.items():
                        if now-last_probe[port]>(.1 if port==8800 else .2):
                            sock.sendto(b'\xef\0\x04\0',(host,port));last_probe[port]=now
                elif now-last_ack>(.025 if sockets[active]==8800 else .05):
                    active.sendto(frames.acknowledgement(now),(host,sockets[active]));last_ack=now
                ready,_,_=select.select(list(sockets),[],[],.01)
                for sock in ready:
                    packet,address=sock.recvfrom(2048)
                    if address[0]!=host or (active is not None and active is not sock):continue
                    parsed=parse_fragment(packet)
                    if parsed is None:continue
                    if parsed['sequence']+64<frames.newest:
                        suspicion+=1
                        if suspicion>=8:frames=Frames(self.header_loader,mode);suspicion=0
                        else:continue
                    else:suspicion=0
                    active=sock
                    image=frames.add(packet,now)
                    if image:
                        with self.lock:
                            self.jpeg=image;self.sequence+=1;self.timestamp=now;self.port=sockets[sock];self.error=''
        except Exception as exc:
            with self.lock:self.error='드론 영상 수신 오류: '+str(exc)
        finally:
            for sock in sockets:sock.close()

    def close(self):
        self.stop_event.set()
        thread=self.thread
        if thread and thread is not threading.current_thread():thread.join(timeout=2)
        self.thread=None
