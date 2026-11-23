"""Suggest boxes with an open pretrained Grounding DINO model; never call them human labels."""
import argparse
import json
from pathlib import Path
import time
from PIL import Image
import torch
from transformers import AutoProcessor,AutoModelForZeroShotObjectDetection

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--limit',type=int,default=10000)
    parser.add_argument('--local-model',type=str)
    args=parser.parse_args()
    torch.set_num_threads(4)
    model_id='IDEA-Research/grounding-dino-tiny'
    print('Loading public model:',model_id,flush=True)
    source_model=args.local_model or model_id
    processor=AutoProcessor.from_pretrained(source_model)
    model=AutoModelForZeroShotObjectDetection.from_pretrained(source_model).eval()
    source=ROOT/'data/candidates.json'
    suggestions=ROOT/'data/box_suggestions.json'
    labels=json.loads(suggestions.read_text()) if suggestions.exists() else {}
    rejected=json.loads((ROOT/'data/rejected.json').read_text()) if (ROOT/'data/rejected.json').exists() else {}
    rows=json.loads(source.read_text(encoding='utf-8'))
    done=0
    for row in rows:
        if row['id'] in labels or row['id'] in rejected or row['group']!='net':
            continue
        image=Image.open(ROOT/row['file']).convert('RGB')
        inputs=processor(images=image,text='fishing net.',return_tensors='pt',size={'shortest_edge':256,'longest_edge':384})
        start=time.monotonic()
        with torch.no_grad():
            outputs=model(**inputs)
        result=processor.post_process_grounded_object_detection(outputs,inputs['input_ids'],threshold=.25,text_threshold=.2,target_sizes=[(image.height,image.width)])[0]
        boxes=[]
        for box,score in zip(result['boxes'],result['scores']):
            x1,y1,x2,y2=box.tolist()
            x1,x2=max(0.,x1/image.width),min(1.,x2/image.width)
            y1,y2=max(0.,y1/image.height),min(1.,y2/image.height)
            if x2>x1 and y2>y1:
                boxes.append({'box':[x1,y1,x2,y2],'score':float(score)})
        labels[row['id']]={'boxes':boxes,'source':model_id,'reviewed':False}
        suggestions.write_text(json.dumps(labels,indent=2),encoding='utf-8')
        done+=1
        print('BOX',len(labels),row['id'],'count',len(boxes),'seconds',round(time.monotonic()-start,2),flush=True)
        if done>=args.limit:
            break


if __name__=='__main__':
    main()
