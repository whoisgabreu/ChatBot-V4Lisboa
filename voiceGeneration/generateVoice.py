import argparse
import wave
from pathlib import Path

from piper import PiperVoice, SynthesisConfig

BASE_DIR = Path(__file__).resolve().parent

DEFAULT_TEXT = (
    "Olá! Eu sou especialista em marketing digital e ajudo pequenas empresas "
    "a dobrarem suas vendas na internet usando anúncios inteligentes. "
    "Se você quer atrair mais clientes todos os dias, vamos conversar agora mesmo."
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Gera áudio com Piper TTS.")
    parser.add_argument("--text", default=DEFAULT_TEXT)
    parser.add_argument("--out", type=Path, default=BASE_DIR / "piper_output.wav")
    parser.add_argument("--voice", type=Path, default=BASE_DIR / "pt_BR-jeff-medium.onnx")
    parser.add_argument("--length-scale", type=float, default=1.0)
    parser.add_argument("--noise-scale", type=float, default=0.667)
    parser.add_argument("--noise-w-scale", type=float, default=0.8)
    parser.add_argument("--volume", type=float, default=1.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.voice.exists():
        raise SystemExit(
            f"Modelo não encontrado: {args.voice}\n"
            "Baixe com: .venv/bin/python -m piper.download_voices pt_BR-jeff-medium --data-dir ."
        )

    voice = PiperVoice.load(str(args.voice))
    syn_config = SynthesisConfig(
        length_scale=args.length_scale,
        noise_scale=args.noise_scale,
        noise_w_scale=args.noise_w_scale,
        volume=args.volume,
    )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(args.out), "wb") as wav_file:
        voice.synthesize_wav(args.text, wav_file, syn_config=syn_config)

    print(f"Áudio gerado: {args.out}")


if __name__ == "__main__":
    main()
