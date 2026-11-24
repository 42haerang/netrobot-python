"""Bundle every runtime asset so the installed APK needs no Internet connection."""
import json
from pathlib import Path
import shutil

ROOT=Path(__file__).resolve().parents[1]


def prepare():
    assets=ROOT/'android/app/src/main/assets'
    shutil.copytree(ROOT/'web',assets/'web',dirs_exist_ok=True)
    models=assets/'web/models'
    models.mkdir(exist_ok=True)
    source=ROOT/'phone/models'
    info=json.loads((source/'model.json').read_text(encoding='utf-8')) if (source/'model.json').is_file() else {}
    ready=info.get('trained_on_net') is True and info.get('names') in (['net'],['fishing_net']) and (source/'net.onnx').is_file()
    if ready:
        shutil.copy2(source/'net.onnx',models/'net.onnx')
        info.update(available=True,file='net.onnx')
    else:
        # Never silently relabel a COCO demo or synthetic fixture as a fishing-net model.
        if (models/'net.onnx').exists():
            raise RuntimeError('Stale bundled model exists; inspect it before building without net weights.')
        info={'available':False,'trained_on_net':False,'status':'Publisher-labeled net training is not complete.'}
    (models/'model.json').write_text(json.dumps(info,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Offline APK assets ready. Net-trained model included:',ready)


if __name__=='__main__':prepare()
