# from funasr import AutoModel
#
# model = AutoModel(
#     model=r"E:\Study-agent-new-master\models\asr\speech_paraformer-large-vad-punc_asr_nat-zh-cn-16k-common-vocab8404-pytorch",
#     vad_model=r"E:\Study-agent-new-master\models\vad\speech_fsmn_vad_zh-cn-16k-common-pytorch",
#     punc_model=r"E:\Study-agent-new-master\models\punc\punc_ct-transformer_cn-en-common-vocab471067-large",
#     sentence_timestamp=True,
# )
#
# res = model.generate(
#     input=r"E:\动漫\bdmv\audio_track1.wav",
#     batch_size_s=300,  # ↓ 降这个通常最有效
#     vad_kwargs={"max_single_segment_time": 30000},  # 30s 一段上限（按需改）
# )
#
#
# def ms2time(ms):
#     h = ms // 3600000
#     ms %= 3600000
#     m = ms // 60000
#     ms %= 60000
#     s = ms // 1000
#     ms %= 1000
#     return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
#
#
# sentences = res[0]["sentence_info"]
#
# with open("output.srt", "w", encoding="utf-8") as f:
#     for idx, s in enumerate(sentences, 1):
#         f.write(f"{idx}\n")
#         f.write(f"{ms2time(s['start'])} --> {ms2time(s['end'])}\n")
#         f.write(s["text"].strip() + "\n\n")
#
# print("✅ 已生成 output.srt")

# from src.application.speech_pipeline import SpeechPipeline
#
# import time
# def main():
#     pipeline = SpeechPipeline()
#
#     try:
#         pipeline.start()
#         print("🎙️ SpeechPipeline 已启动，开始说话吧！（Ctrl+C 停止）")
#
#         while True:
#             time.sleep(0.2)
#
#     except KeyboardInterrupt:
#         print("\n🛑 正在停止 SpeechPipeline...")
#
#     finally:
#         pipeline.stop()
#         print("✅ 已停止")
#
#
# if __name__ == "__main__":
#     main()


from src.application.vedio_transcriber import VedioTranscriber

vt = VedioTranscriber()
vt.start(r"E:\Study-agent-new-master\models\asr\SenseVoiceSmall\example\zh.mp3")