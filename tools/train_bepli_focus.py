"""Fine-tune real object crops; select at phone resolution before fresh testing."""
import argparse
import json
import os
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
os.environ.setdefault('YOLO_CONFIG_DIR',str(ROOT/'models/.yolo'))
os.environ.setdefault('YOLO_AUTOINSTALL','false')


def train(dataset, initial, epochs):
    import torch
    from ultralytics import YOLO
    dataset=Path(dataset).resolve()
    report=json.loads((dataset/'report.json').read_text())
    if not report.get('previous_baseline_test_retired') or len(report.get('retired_test_ids_excluded',[]))!=200:
        raise ValueError('The previously examined test images must be excluded')
    rows=json.loads((dataset/'manifest.json').read_text(encoding='utf-8'))
    if any(r['source_id'] in report['retired_test_ids_excluded'] for r in rows if r['split']=='test'):
        raise ValueError('Retired image reused in final test')
    def threads(_):torch.set_num_threads(4)
    def cache(trainer):
        threads(trainer)
        d=trainer.train_loader.dataset
        d.cache='ram'
        d.cache_images()
    def finite(trainer):
        for key,value in trainer.ema.ema.state_dict().items():
            if value.is_floating_point() and (not torch.isfinite(value).all() or value.abs().max()>65504):
                raise RuntimeError('Unstable checkpoint: '+key)
    model=YOLO(str(initial))
    model.add_callback('on_train_start',cache)
    model.add_callback('on_train_epoch_start',threads)
    model.add_callback('on_val_start',threads)
    model.add_callback('on_train_epoch_end',finite)
    # This starts a new optimizer; half-precision saved optimizer moments are
    # never resumed. Only the finite final baseline network weights transfer.
    model.train(data=str(dataset/'data.yaml'),epochs=epochs,imgsz=320,batch=16,
        device='cpu',workers=0,project=str(ROOT/'models/runs'),name='bepli_focus',
        exist_ok=False,patience=0,amp=False,plots=False,seed=2027,deterministic=True,
        cache=False,close_mosaic=2,optimizer='AdamW',lr0=0.0003,momentum=0.9,
        nbs=16,freeze=10,warmup_epochs=1,warmup_bias_lr=0.0001,verbose=False)
    candidates=sorted({Path(model.trainer.best),Path(model.trainer.last)})
    validation=[]
    for checkpoint in candidates:
        candidate=YOLO(str(checkpoint))
        candidate.add_callback('on_val_start',threads)
        metrics=candidate.val(data=str(dataset/'data.yaml'),split='val',imgsz=640,
            batch=8,device='cpu',workers=0,plots=False,verbose=False)
        validation.append((float(metrics.box.map50),checkpoint))
    score,chosen=max(validation,key=lambda item:item[0])
    if score<=0:
        raise RuntimeError('No valid validation detections; do not consume the fresh test set or export')
    model=YOLO(str(chosen))
    model.add_callback('on_val_start',threads)
    metrics=model.val(data=str(dataset/'data.yaml'),split='test',imgsz=640,
        batch=8,device='cpu',workers=0,plots=False,verbose=False)
    summary={'dataset':report,'crop_epochs':epochs,'prior_full_frame_epochs':20,
        'initialization':str(Path(initial).name),'training_size':320,'phone_size':640,
        'model_selection':'Higher validation mAP50 at 640 between best/last crop checkpoints, before final test',
        'validation_candidates':[{'checkpoint':p.name,'mAP50':s} for s,p in validation],
        'selected_checkpoint':str(chosen.relative_to(ROOT)),
        'fresh_held_out_test_evaluations':1,
        'metrics':{k:float(v) for k,v in metrics.results_dict.items()},
        'previous_failed_baseline_test_images':200,'previous_test_ids_retired':True}
    (ROOT/'models/bepli_focus_test_metrics.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    if float(metrics.box.map50)<=0:
        raise RuntimeError('Fresh held-out test has zero mAP; this model must not be bundled')
    from export_phone import export
    export(chosen,trained=True,size=640)
    path=ROOT/'phone/models/model.json'
    info=json.loads(path.read_text())
    info.update(dataset='BePLi v2',dataset_doi='10.17882/96963',dataset_license='CC BY-NC-SA 4.0',
        model_revision='bepli-focus-v2',train_images=700,validation_images=100,test_images=200,
        test_metrics=summary['metrics'],validated_for_bundle=False)
    path.write_text(json.dumps(info,indent=2),encoding='utf-8')
    print('FOCUS_TRAINING_AND_EXPORT_COMPLETE',json.dumps(summary['metrics']),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('dataset',type=Path)
    parser.add_argument('initial',type=Path)
    parser.add_argument('--epochs',type=int,default=8)
    args=parser.parse_args()
    train(args.dataset,args.initial,args.epochs)
