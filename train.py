"""그물 YOLO 학습과 ONNX 내보내기를 한곳에서 실행합니다."""

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parent
os.environ.setdefault("YOLO_CONFIG_DIR", str(ROOT / "models/.yolo"))
os.environ.setdefault("YOLO_AUTOINSTALL", "false")


# 그물 한 종류 모델인지 확인하고 OpenCV용 고정 크기 ONNX로 내보냅니다.
def export(weights, trained=True, size=640):
    from ultralytics import YOLO
    import torch

    model = YOLO(str(weights))
    names = [model.names[i] for i in range(len(model.names))]
    if trained and names not in (["net"], ["fishing_net"]):
        raise ValueError("A net-trained export must have exactly one net class")
    if any(
        value.is_floating_point() and not torch.isfinite(value).all()
        for value in model.model.state_dict().values()
    ):
        raise ValueError("Non-finite checkpoint values; do not deploy this model")
    output = model.export(
        format="onnx",
        imgsz=size,
        batch=1,
        opset=12,
        simplify=False,
        dynamic=False,
        nms=False,
        device="cpu",
    )
    folder = ROOT / "models"
    folder.mkdir(exist_ok=True)
    if Path(output).resolve() != (folder / "net.onnx").resolve():
        shutil.copy2(output, folder / "net.onnx")
    with (folder / "net.onnx").open("rb") as checkpoint:
        digest = hashlib.file_digest(checkpoint, "sha256").hexdigest()
    info = {
        "size": size,
        "names": names,
        "trained_on_net": trained,
        "sha256": digest,
        "validated_for_bundle": False,
        "source_checkpoint": str(Path(weights).name),
        "framework": "Ultralytics YOLOv8, OpenCV DNN, ONNX opset 12",
    }
    (folder / "model.json").write_text(
        json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("EXPORTED", folder / "net.onnx", flush=True)
    return folder / "net.onnx"


# 내보낸 ONNX와 원래 PyTorch가 같은 숫자를 출력하는지 검증 사진으로 비교합니다.
def check(weights, image_path):
    import cv2
    import numpy as np
    import onnx
    import torch
    from ultralytics import YOLO

    info_path = ROOT / "models/model.json"
    info = json.loads(info_path.read_text(encoding="utf-8"))
    model_path = ROOT / "models/net.onnx"
    if hashlib.sha256(model_path.read_bytes()).hexdigest() != info["sha256"]:
        raise ValueError("ONNX와 모델 설명의 SHA256이 다릅니다.")
    onnx.checker.check_model(onnx.load(str(model_path)), full_check=True)

    # 실제 화면과 같이 긴 변을 640에 맞추고 남은 곳을 회색으로 채웁니다.
    image = cv2.imdecode(np.fromfile(image_path, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("검증 사진을 읽을 수 없습니다.")
    height, width = image.shape[:2]
    size = info["size"]
    scale = min(size / width, size / height)
    nw, nh = math.floor(width * scale + 0.5), math.floor(height * scale + 0.5)
    left, top = (size - nw) // 2, (size - nh) // 2
    canvas = np.full((size, size, 3), 114, dtype=np.uint8)
    canvas[top : top + nh, left : left + nw] = cv2.resize(image, (nw, nh))
    tensor = np.ascontiguousarray(
        canvas[..., ::-1].transpose(2, 0, 1)[None] / 255, dtype=np.float32
    )

    # 동일한 입력으로 원래 모델과 ONNX를 각각 한 번 실행합니다.
    torch.set_num_threads(1)
    original = YOLO(str(weights)).model.float().eval()
    with torch.inference_mode():
        expected = original(torch.from_numpy(tensor))[0].numpy()
    exported = cv2.dnn.readNetFromONNX(np.frombuffer(model_path.read_bytes(), dtype=np.uint8))
    exported.setInput(tensor)
    actual = exported.forward()
    count = (size // 8) ** 2 + (size // 16) ** 2 + (size // 32) ** 2
    if actual.shape != (1, 5, count) or not np.isfinite(actual).all():
        raise ValueError("그물 한 종류 모델의 출력 형식이 아닙니다.")
    if not np.allclose(actual[:, :4], expected[:, :4], rtol=0.0001, atol=0.05) or not np.allclose(
        actual[:, 4:], expected[:, 4:], rtol=0.0001, atol=0.00001
    ):
        raise ValueError("ONNX와 원래 모델의 추론 결과가 다릅니다.")

    # 수치 검사와 탐지 성능 평가는 별개입니다. 테스트 지표도 있어야 빌드에 넣습니다.
    metrics = info.get("test_metrics", {})
    if not info.get("trained_on_net") or metrics.get("metrics/mAP50(B)", 0) <= 0:
        raise ValueError("먼저 별도 테스트에서 그물 탐지 지표를 기록하세요.")
    info["validated_for_bundle"] = True
    info["cpu_export_check"] = {
        "image": Path(image_path).name,
        "finite": True,
        "maximum_difference": float(np.abs(actual - expected).max()),
        "scope": "PC OpenCV와 PyTorch 비교. 실제 로봇 카메라 성능 검증은 별도.",
    }
    info_path.write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
    print("ONNX와 PyTorch 수치 검사 통과.")


# 검증 사진으로 후보를 고른 후, 새 테스트 사진에서 한 번 평가합니다.
def train(dataset, initial, epochs):
    import torch
    from ultralytics import YOLO

    dataset = Path(dataset).resolve()
    # 폴더를 옮겨도 학습 사진을 찾도록 실행할 때 절대 경로 설정을 만듭니다.
    config = ROOT / "models/.yolo/dataset.yaml"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(json.dumps({"path": str(dataset), "train": "images/train",
                                "val": "images/val", "test": "images/test", "names": {0: "net"}}), encoding="utf-8")
    report = json.loads((dataset / "report.json").read_text())
    if (
        not report.get("previous_baseline_test_retired")
        or len(report.get("retired_test_ids_excluded", [])) != 200
    ):
        raise ValueError("The previously examined test images must be excluded")
    rows = json.loads((dataset / "manifest.json").read_text(encoding="utf-8"))
    if any(
        r["source_id"] in report["retired_test_ids_excluded"] for r in rows if r["split"] == "test"
    ):
        raise ValueError("Retired image reused in final test")

    # CPU가 과도한 스레드를 만들지 않도록 제한합니다.
    def threads(_):
        torch.set_num_threads(4)

    # 학습 사진은 메모리에 두어 같은 파일을 반복해서 읽지 않습니다.
    def cache(trainer):
        threads(trainer)
        d = trainer.train_loader.dataset
        d.cache = "ram"
        d.cache_images()

    # 학습 중 숫자가 무한대가 되면 잘못된 가중치를 배포하지 않고 멈춥니다.
    def finite(trainer):
        for key, value in trainer.ema.ema.state_dict().items():
            if value.is_floating_point() and (
                not torch.isfinite(value).all() or value.abs().max() > 65504
            ):
                raise RuntimeError("Unstable checkpoint: " + key)

    model = YOLO(str(initial))
    model.add_callback("on_train_start", cache)
    model.add_callback("on_train_epoch_start", threads)
    model.add_callback("on_val_start", threads)
    model.add_callback("on_train_epoch_end", finite)
    # 초기 모델의 가중치만 가져오고 새 학습 상태로 시작합니다.
    model.train(
        data=str(config),
        epochs=epochs,
        imgsz=320,
        batch=16,
        device="cpu",
        workers=0,
        project=str(ROOT / "models/runs"),
        name="bepli_focus",
        exist_ok=False,
        patience=0,
        amp=False,
        plots=False,
        seed=2027,
        deterministic=True,
        cache=False,
        close_mosaic=2,
        optimizer="AdamW",
        lr0=0.0003,
        momentum=0.9,
        nbs=16,
        freeze=10,
        warmup_epochs=1,
        warmup_bias_lr=0.0001,
        verbose=False,
    )
    # 검증 점수가 좋은 후보를 고른 후에만 테스트 사진을 사용합니다.
    candidates = sorted({Path(model.trainer.best), Path(model.trainer.last)})
    validation = []
    for checkpoint in candidates:
        candidate = YOLO(str(checkpoint))
        candidate.add_callback("on_val_start", threads)
        metrics = candidate.val(
            data=str(config),
            split="val",
            imgsz=640,
            batch=8,
            device="cpu",
            workers=0,
            plots=False,
            verbose=False,
        )
        validation.append((float(metrics.box.map50), checkpoint))
    score, chosen = max(validation, key=lambda item: item[0])
    if score <= 0:
        raise RuntimeError(
            "No valid validation detections; do not consume the fresh test set or export"
        )
    model = YOLO(str(chosen))
    model.add_callback("on_val_start", threads)
    metrics = model.val(
        data=str(config),
        split="test",
        imgsz=640,
        batch=8,
        device="cpu",
        workers=0,
        plots=False,
        verbose=False,
    )
    summary = {
        "dataset": report,
        "crop_epochs": epochs,
        "prior_full_frame_epochs": 20,
        "initialization": str(Path(initial).name),
        "training_size": 320,
        "inference_size": 640,
        "model_selection": "Higher validation mAP50 at 640 between best/last crop checkpoints, before final test",
        "validation_candidates": [{"checkpoint": p.name, "mAP50": s} for s, p in validation],
        "selected_checkpoint": str(chosen.relative_to(ROOT)),
        "fresh_held_out_test_evaluations": 1,
        "metrics": {k: float(v) for k, v in metrics.results_dict.items()},
        "previous_failed_baseline_test_images": 200,
        "previous_test_ids_retired": True,
    }
    (ROOT / "models/bepli_focus_test_metrics.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    if float(metrics.box.map50) <= 0:
        raise RuntimeError("Fresh held-out test has zero mAP; this model must not be bundled")
    export(chosen, trained=True, size=640)
    path = ROOT / "models/model.json"
    info = json.loads(path.read_text())
    info.update(
        dataset="BePLi v2",
        dataset_doi="10.17882/96963",
        dataset_license="CC BY-NC-SA 4.0",
        model_revision="bepli-focus-v2",
        train_images=700,
        validation_images=100,
        test_images=200,
        test_metrics=summary["metrics"],
        validated_for_bundle=False,
    )
    path.write_text(json.dumps(info, indent=2), encoding="utf-8")
    print("FOCUS_TRAINING_AND_EXPORT_COMPLETE", json.dumps(summary["metrics"]), flush=True)


# 학습과 내보내기 중 필요한 명령만 선택합니다.
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    training = commands.add_parser("train")
    training.add_argument("dataset", type=Path)
    training.add_argument("initial", type=Path)
    training.add_argument("--epochs", type=int, default=8)
    exporting = commands.add_parser("export")
    exporting.add_argument("weights", type=Path)
    checking = commands.add_parser("check")
    checking.add_argument("weights", type=Path)
    checking.add_argument("validation_image", type=Path)
    args = parser.parse_args()
    if args.command == "train":
        train(args.dataset, args.initial, args.epochs)
    elif args.command == "export":
        export(args.weights)
    else:
        check(args.weights, args.validation_image)


if __name__ == "__main__":
    main()
