import sounddevice as sd

stream = sd.InputStream(
    samplerate=16000,
    channels=1,
    blocksize=512,


)