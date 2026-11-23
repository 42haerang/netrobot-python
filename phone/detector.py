"""YOLOv8 ONNX inference with OpenCV DNN, on the phone's own CPU."""
from pathlib import Path
import json
import cv2
import numpy as np


class Detector:
    def __init__(self,folder):
        folder=Path(folder)
        self.info=json.loads((folder/'model.json').read_text(encoding='utf-8'))
        self.size=int(self.info.get('size',320))
        self.names=self.info['names']
        self.net=cv2.dnn.readNetFromONNX(str(folder/'net.onnx'))
        self.net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
        self.net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
        cv2.setNumThreads(2)

    def predict(self,frame,threshold=.4):
        h,w=frame.shape[:2]
        scale=min(self.size/w,self.size/h)
        nw,nh=round(w*scale),round(h*scale)
        left,top=(self.size-nw)//2,(self.size-nh)//2
        padded=np.full((self.size,self.size,3),114,dtype=np.uint8)
        padded[top:top+nh,left:left+nw]=cv2.resize(frame,(nw,nh))
        blob=cv2.dnn.blobFromImage(padded,1/255.,(self.size,self.size),swapRB=True,crop=False)
        self.net.setInput(blob)
        output=self.net.forward()
        rows=np.asarray(output)[0].T
        if rows.shape[1]!=4+len(self.names):
            raise ValueError('Model output and class names do not match; export YOLOv8 with nms=False')
        boxes,scores,classes=[],[],[]
        for row in rows:
            index=int(np.argmax(row[4:]))
            score=float(row[4+index])
            if score<threshold:
                continue
            cx,cy,bw,bh=map(float,row[:4])
            x1=max(0,min(w-1,(cx-bw/2-left)/scale))
            y1=max(0,min(h-1,(cy-bh/2-top)/scale))
            x2=max(0,min(w-1,(cx+bw/2-left)/scale))
            y2=max(0,min(h-1,(cy+bh/2-top)/scale))
            if x2<=x1 or y2<=y1:
                continue
            boxes.append([int(x1),int(y1),int(x2-x1),int(y2-y1)])
            scores.append(score)
            classes.append(index)
        results=[]
        for cls in sorted(set(classes)):
            selected=[i for i,value in enumerate(classes) if value==cls]
            keep=cv2.dnn.NMSBoxes([boxes[i] for i in selected],[scores[i] for i in selected],threshold,.45)
            for local in np.asarray(keep).reshape(-1):
                i=selected[int(local)]
                x,y,bw,bh=boxes[i]
                results.append({'name':self.names[cls],'score':scores[i],'box':[x,y,x+bw,y+bh]})
        return results


def draw(frame,results):
    image=frame.copy()
    for result in results:
        x1,y1,x2,y2=result['box']
        cv2.rectangle(image,(x1,y1),(x2,y2),(90,225,120),2)
        text=f"{result['name']} {result['score']:.0%}"
        cv2.putText(image,text,(x1,max(22,y1-6)),cv2.FONT_HERSHEY_SIMPLEX,.6,(90,225,120),2,cv2.LINE_AA)
    return image
