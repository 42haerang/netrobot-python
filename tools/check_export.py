"""Compare the trained PyTorch output with the APK's bundled WASM on one image.

Use a validation image, not a held-out test image. Intermediate arrays remain
in the specified work directory. This checks export/runtime agreement, not
detection accuracy or Android device performance.
"""
import argparse
import json
import math
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault('YOLO_AUTOINSTALL', 'false')
os.environ.setdefault('YOLO_CONFIG_DIR', str(ROOT/'models/.yolo'))


def check(weights, image_path, output):
    import cv2
    import numpy as np
    import onnx
    import torch
    from ultralytics import YOLO
    torch.set_num_threads(1)
    model_path = ROOT/'phone/models/net.onnx'
    size=json.loads((ROOT/'phone/models/model.json').read_text())['size']
    graph = onnx.load(str(model_path))
    onnx.checker.check_model(graph, full_check=True)
    for initializer in graph.graph.initializer:
        array = onnx.numpy_helper.to_array(initializer)
        if np.issubdtype(array.dtype, np.floating) and not np.isfinite(array).all():
            raise ValueError('Non-finite ONNX tensor: '+initializer.name)
    image = cv2.imdecode(np.fromfile(image_path, dtype=np.uint8), cv2.IMREAD_COLOR)
    h, w = image.shape[:2]
    scale = min(size/w, size/h)
    nw, nh = math.floor(w*scale+.5), math.floor(h*scale+.5)
    left, top = (size-nw)//2, (size-nh)//2
    canvas = np.full((size, size, 3), 114, dtype=np.uint8)
    canvas[top:top+nh, left:left+nw] = cv2.resize(image, (nw, nh))
    tensor = np.ascontiguousarray(canvas[..., ::-1].transpose(2, 0, 1)[None]/255, dtype=np.float32)
    model = YOLO(str(weights)).model.float().eval()
    with torch.inference_mode():
        expected = model(torch.from_numpy(tensor))[0].numpy()
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    input_path, result_path = output/'input.f32', output/'wasm_output.f32'
    tensor.tofile(input_path)
    command = ['node', str(ROOT/'tools/check_wasm.mjs'), str(model_path), str(input_path), str(result_path),str(size)]
    wasm = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=True, timeout=120)
    actual = np.fromfile(result_path, dtype=np.float32).reshape(expected.shape)
    count=(size//8)**2+(size//16)**2+(size//32)**2
    if expected.shape != (1, 5, count) or not np.isfinite(expected).all() or not np.isfinite(actual).all():
        raise ValueError('Invalid single-class output')
    difference = float(np.max(np.abs(actual-expected)))
    if (not np.allclose(actual[:, :4], expected[:, :4], rtol=0.0001, atol=0.05)
            or not np.allclose(actual[:, 4:], expected[:, 4:], rtol=0.0001, atol=0.00001)):
        raise ValueError('WASM/PyTorch output mismatch: '+str(difference))
    report = {'image': Path(image_path).name, 'output_shape': list(actual.shape),
              'max_absolute_difference': difference, 'allclose_rtol': 0.0001,
              'box_allclose_atol': 0.05, 'confidence_allclose_atol': 0.00001,
              'max_confidence_difference': float(np.max(np.abs(actual[:, 4:]-expected[:, 4:]))), 'finite': True,
              'engine_report': json.loads(wasm.stdout.strip().splitlines()[-1]),
              'scope': 'Bundled WASM on Windows Node; not Android device validation'}
    (output/'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print('EXPORT_PARITY_OK', json.dumps(report), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('weights', type=Path)
    parser.add_argument('validation_image', type=Path)
    parser.add_argument('output_directory', type=Path)
    args = parser.parse_args()
    check(args.weights, args.validation_image, args.output_directory)
