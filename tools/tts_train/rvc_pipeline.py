import argparse
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def find_exe(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise FileNotFoundError(f"{name} not found in PATH. Install it or add it to PATH.")
    return path


def run_cmd(cmd):
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode, result.stdout, result.stderr


def convert_with_rvc(input_path: Path, output_path: Path, speaker_id: str, model_dir: Path = None, extra_args: str = None):
    rvc = find_exe("rvc")
    cmd = [rvc, "-i", str(input_path), "-o", str(output_path), "--speaker", speaker_id]
    if model_dir:
        cmd += ["--model-dir", str(model_dir)]
    if extra_args:
        cmd += extra_args.split()
    return run_cmd(cmd)


def main():
    parser = argparse.ArgumentParser(description="Run RVC-based accent / timbre conversion on raw voice audio.")
    parser.add_argument("kol_id", help="KOL ID, e.g. sofia-vargas")
    parser.add_argument("--input", help="Source raw audio file in kols/<id>/voice/raw/", required=True)
    parser.add_argument("--output", help="Output converted audio file relative to kols/<id>/voice/raw/", default="converted_western.wav")
    parser.add_argument("--speaker", help="Speaker or target timbre name for the RVC model", required=True)
    parser.add_argument("--model-dir", help="Optional path to the RVC model directory.")
    parser.add_argument("--extra-args", help="Additional CLI args passed to the RVC command.")
    args = parser.parse_args()

    raw_dir = REPO_ROOT / "kols" / args.kol_id / "voice" / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    src = raw_dir / args.input
    if not src.exists():
        raise FileNotFoundError(f"Source audio not found: {src}")

    dst = raw_dir / args.output
    model_dir = Path(args.model_dir) if args.model_dir else None
    code, out, err = convert_with_rvc(src, dst, args.speaker, model_dir=model_dir, extra_args=args.extra_args)
    if code != 0:
        raise RuntimeError(f"RVC conversion failed:\n{err}")

    print(f"Converted audio written to {dst}")
    print(out)


if __name__ == "__main__":
    main()
