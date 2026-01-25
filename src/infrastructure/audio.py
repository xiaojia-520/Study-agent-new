import numpy as np


def indata_to_mono_float32(indata: np.ndarray) -> np.ndarray:
    audio = np.asarray(indata, dtype=np.float32)

    if audio.ndim == 1:
        return audio

    if audio.ndim == 2:
        if audio.shape[1] == 1:
            return audio[:, 0]
        return audio.mean(axis=1)

    return audio.reshape(-1)
