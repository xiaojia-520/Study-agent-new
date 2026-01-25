import sounddevice as sd


def s(callback):
    stream = sd.InputStream(
        samplerate=16000,
        channels=1,
        blocksize=512,
        device=3,
        callback=callback,
    )
    return stream.start()

