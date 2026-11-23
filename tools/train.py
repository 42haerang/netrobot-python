"""Train YOLO on 800 photos, then evaluate the untouched 200-photo test once."""
import argparse
import json
import os
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
os.environ.setdefault('YOLO_CONFIG_DIR',str(ROOT/'models/.yolo'))
os.environ.setdefault('YOLO_AUTOINSTALL','false')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--epochs',type=int,default=20)
    args=parser.parse_args()
    from ultralytics import YOLO
    import torch
    torch.set_num_threads(4)
    report=json.loads((ROOT/'data/dataset_report.json').read_text())
    assert report['total']==1000 and report['train']==800 and report['test']==200
    data=ROOT/'data/dataset'
    # All 800 photos are used for training. No early stopping or test-based model selection.
    config='path: '+json.dumps(data.as_posix())+'\ntrain: images/train\nval: images/train\ntest: images/test\nnames:\n  0: net\n'
    yaml=data/'data.yaml'
    yaml.write_text(config,encoding='utf-8')
    model=YOLO(str(ROOT/'models/yolov8n.pt'))
    model.train(data=str(yaml),epochs=args.epochs,imgsz=320,batch=8,device='cpu',workers=0,
                project=str(ROOT/'models/runs'),name='net',exist_ok=False,val=False,patience=0,
                amp=False,plots=False,seed=2027,deterministic=True,cache=False,close_mosaic=0)
    # Ultralytics can perform a final training-set validation even when val=False.
    # Always deploy the final checkpoint, never select best.pt using the held-out test.
    final=Path(model.trainer.last)
    chosen=YOLO(str(final))
    metrics=chosen.val(data=str(yaml),split='test',imgsz=320,device='cpu',workers=0,plots=False)
    (ROOT/'models/test_metrics.json').write_text(json.dumps({key:float(value) for key,value in metrics.results_dict.items()},indent=2))
    from export_phone import export
    export(final,trained=True)
    print('Train=800; held-out test=200; deployed final epoch, not test-selected best.',flush=True)


if __name__=='__main__':
    main()
