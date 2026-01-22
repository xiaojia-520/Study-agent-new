from src.application.speech_pipeline import SpeechPipeline


def main():
    app = SpeechPipeline()
    app.start()
    input("按回车结束...\n")
    app.stop()


if __name__ == "__main__":
    main()
