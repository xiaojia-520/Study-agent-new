import ffmpeg
from src.core.asr.transcriber import VEDIOTranscriber
import os


class VedioTranscriber:

    def __init__(self):
        self.vediotransciber = VEDIOTranscriber()

    import os
    import ffmpeg

    def prepare_funasr_wav(self, input_path: str, output_dir: str = "./tmp_wav") -> str:
        """
        统一把输入(音频/视频)处理成 FunASR 友好的 wav：
        - 16kHz
        - mono
        - PCM_s16le
        - 若是视频：提取第一条音轨（0:a:0）
        返回：wav_path（你可以直接 res = wav_path）
        """
        os.makedirs(output_dir, exist_ok=True)
        base = os.path.splitext(os.path.basename(input_path))[0]
        wav_path = os.path.join(output_dir, f"{base}_16k_mono.wav")

        probe = ffmpeg.probe(input_path)
        streams = probe.get("streams", [])
        has_video = any(s.get("codec_type") == "video" for s in streams)
        has_audio = any(s.get("codec_type") == "audio" for s in streams)
        if not has_audio:
            raise ValueError(f"文件里没有音频流：{input_path}")

        inp = ffmpeg.input(input_path)

        # 视频：显式 map 第一条音轨；音频：不需要 map 也行（但写了也更稳）
        out_kwargs = dict(
            format="wav",
            acodec="pcm_s16le",
            ac=1,  # mono
            ar=16000,  # 16k
        )
        if has_video:
            out_kwargs["map"] = "0:a:0"

        (
            inp.output(wav_path, **out_kwargs)
            .overwrite_output()
            .run(quiet=True)
        )

        return wav_path

    def start(self, path):
        wav_path = self.prepare_funasr_wav(path)
        res = self.vediotransciber.transcribe(wav_path)
        print(res)
