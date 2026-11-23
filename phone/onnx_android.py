"""Android-only Python adapter for the bundled ONNX Runtime Android library."""
from pathlib import Path
import json
import numpy as np
from java import jarray,jint,jfloat,jlong
from java.nio import FloatBuffer
from java.util import HashMap
from android.graphics import Bitmap,Canvas,Color,Paint
from ai.onnxruntime import OrtEnvironment,OrtSession,OnnxTensor


class Detector:
    def __init__(self,folder):
        folder=Path(folder)
        self.info=json.loads((folder/'model.json').read_text(encoding='utf-8'))
        self.size=int(self.info['size'])
        self.names=self.info['names']
        self.env=OrtEnvironment.getEnvironment()
        options=OrtSession.SessionOptions()
        options.setIntraOpNumThreads(2)
        options.setInterOpNumThreads(1)
        self.session=self.env.createSession(str(folder/'net.onnx'),options)
        self.input_name=str(self.session.getInputNames().iterator().next())

    def predict(self,bitmap,threshold=.4):
        width,height=bitmap.getWidth(),bitmap.getHeight()
        scale=min(self.size/width,self.size/height)
        nw,nh=round(width*scale),round(height*scale)
        left,top=(self.size-nw)//2,(self.size-nh)//2
        small=Bitmap.createScaledBitmap(bitmap,nw,nh,True)
        padded=Bitmap.createBitmap(self.size,self.size,Bitmap.Config.ARGB_8888)
        canvas=Canvas(padded)
        canvas.drawColor(Color.rgb(114,114,114))
        canvas.drawBitmap(small,float(left),float(top),None)
        pixels=jarray(jint)(self.size*self.size)
        padded.getPixels(pixels,0,self.size,0,0,self.size,self.size)
        raw=np.array(pixels,dtype=np.int32).view(np.uint32)
        rgb=np.stack(((raw>>16)&255,(raw>>8)&255,raw&255)).astype(np.float32)/255.
        floats=FloatBuffer.wrap(jarray(jfloat)(rgb.reshape(-1)))
        tensor=OnnxTensor.createTensor(self.env,floats,jarray(jlong)([1,3,self.size,self.size]))
        inputs=HashMap()
        inputs.put(self.input_name,tensor)
        output=None
        try:
            output=self.session.run(inputs)
            rows=np.array(output.get(0).getValue()[0],dtype=np.float32).T
            if rows.shape[1]!=4+len(self.names):
                raise ValueError('ONNX output shape does not match model.json')
            confidence=np.max(rows[:,4:],axis=1)
            keep=np.flatnonzero(confidence>=threshold)
            boxes=[]
            for i in keep:
                cx,cy,bw,bh=map(float,rows[i,:4])
                box=[max(0.,(cx-bw/2-left)/scale),max(0.,(cy-bh/2-top)/scale),
                     min(float(width),(cx+bw/2-left)/scale),min(float(height),(cy+bh/2-top)/scale)]
                if box[2]>box[0] and box[3]>box[1]:
                    boxes.append({'box':box,'score':float(confidence[i]),'class':int(np.argmax(rows[i,4:]))})
            results=[]
            while boxes and len(results)<40:
                best=max(boxes,key=lambda b:b['score'])
                boxes.remove(best)
                results.append(best)
                a=best['box']
                remaining=[]
                for candidate in boxes:
                    b=candidate['box']
                    intersection=max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))
                    union=(a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-intersection
                    if candidate['class']!=best['class'] or intersection/max(union,1e-9)<.45:
                        remaining.append(candidate)
                boxes=remaining
            return [{'box':b['box'],'score':b['score'],'name':self.names[b['class']]} for b in results]
        finally:
            if output is not None:
                output.close()
            tensor.close()
            padded.recycle()
            if small is not bitmap:
                small.recycle()

    def close(self):
        self.session.close()


def draw(bitmap,results):
    output=bitmap.copy(Bitmap.Config.ARGB_8888,True)
    canvas=Canvas(output)
    paint=Paint()
    paint.setAntiAlias(True)
    paint.setColor(Color.rgb(70,245,150))
    paint.setStrokeWidth(3.)
    paint.setTextSize(24.)
    for row in results:
        x1,y1,x2,y2=row['box']
        paint.setStyle(Paint.Style.STROKE)
        canvas.drawRect(float(x1),float(y1),float(x2),float(y2),paint)
        paint.setStyle(Paint.Style.FILL)
        canvas.drawText(f"{row['name']} {row['score']:.0%}",float(x1),float(max(26,y1-5)),paint)
    return output
