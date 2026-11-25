"""Train on publisher BePLi labels, select with validation, test once, export."""
import argparse
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault('YOLO_CONFIG_DIR', str(ROOT/'models/.yolo'))
os.environ.setdefault('YOLO_AUTOINSTALL', 'false')


def train(dataset, epochs, threads):
    import torch
    torch.set_num_threads(threads)
    from ultralytics import YOLO
    dataset = Path(dataset).resolve()
    report = json.loads((dataset/'report.json').read_text(encoding='utf-8'))
    if (report.get('source') != 'BePLi v2' or report.get('legacy_search_images') != 0
            or not report.get('publisher_splits_preserved') or report.get('total') != 1000):
        raise ValueError('Expected audited publisher dataset from prepare_bepli.py')
    if (report['train'], report['val'], report['test']) != (700, 100, 200):
        raise ValueError('Unexpected split; preserve the held-out test')
    model = YOLO(str(ROOT/'models/yolov8n.pt'))
    # select_device resets PyTorch's CPU thread count. Restore the requested
    # bound after trainer/validator setup to avoid oversubscribing this laptop.
    def limit_threads(_):
        torch.set_num_threads(threads)
    def cache_training_images(trainer):
        limit_threads(trainer)
        images = trainer.train_loader.dataset
        if images.cache != 'ram':
            images.cache = 'ram'
            images.cache_images()
        print('CPU_THREADS', torch.get_num_threads(), 'RAM_IMAGE_CACHE', len(images.ims), flush=True)
    def check_weights(trainer):
        for key, value in trainer.ema.ema.state_dict().items():
            if value.is_floating_point() and (not torch.isfinite(value).all() or value.abs().max() > 65504):
                raise RuntimeError('Unstable weights cannot be stored safely in the checkpoint: '+key)
    model.add_callback('on_train_start', cache_training_images)
    model.add_callback('on_train_epoch_start', limit_threads)
    model.add_callback('on_val_start', limit_threads)
    model.add_callback('on_train_epoch_end', check_weights)
    model.train(data=str(dataset/'data.yaml'), epochs=epochs, imgsz=320, batch=16,
                device='cpu', workers=0, project=str(ROOT/'models/runs'),
                name='bepli_net', exist_ok=False, val=True, patience=0, amp=False,
                plots=False, seed=2027, deterministic=True, cache=False,
                close_mosaic=min(5, epochs), verbose=False,
                optimizer='AdamW', lr0=0.0005, momentum=0.9, nbs=16, freeze=10)
    chosen = Path(model.trainer.best)
    model = YOLO(str(chosen))
    model.add_callback('on_val_start', limit_threads)
    # Only this final evaluation uses the held-out images. Never select epochs,
    # confidence thresholds or hyperparameters from its results.
    metrics = model.val(data=str(dataset/'data.yaml'), split='test', imgsz=320,
                        batch=16, device='cpu', workers=0, plots=False, verbose=False)
    summary = {'dataset': report, 'epochs': epochs, 'imgsz': 320,
               'initialization': 'COCO YOLOv8n, first 10 backbone modules frozen',
               'optimizer': 'AdamW, lr0=0.0005, batch=16, nbs=16',
               'model_selection': 'best validation mAP on the 100-image validation set',
               'held_out_test_evaluations': 1,
               'metrics': {key: float(value) for key, value in metrics.results_dict.items()},
               'limitations': ['First baseline on public beach photos, not the user drone camera domain.',
                               'No guarantee of detection on unseen net types or backgrounds.',
                               'Confidence is a model score, not measured precision.']}
    metrics_path = ROOT/'models/bepli_test_metrics.json'
    metrics_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    from export_phone import export
    export(chosen, trained=True)
    manifest = ROOT/'phone/models/model.json'
    info = json.loads(manifest.read_text(encoding='utf-8'))
    info.update(dataset='BePLi v2', dataset_doi='10.17882/96963',
                dataset_license='CC BY-NC-SA 4.0', train_images=700,
                validation_images=100, test_images=200, epochs=epochs,
                test_metrics=summary['metrics'], model_revision='bepli-v1')
    manifest.write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding='utf-8')
    print('TRAINING_AND_EXPORT_COMPLETE', json.dumps(summary['metrics']), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('dataset', type=Path)
    parser.add_argument('--epochs', type=int, default=20)
    parser.add_argument('--threads', type=int, default=4)
    args = parser.parse_args()
    train(args.dataset, args.epochs, args.threads)
