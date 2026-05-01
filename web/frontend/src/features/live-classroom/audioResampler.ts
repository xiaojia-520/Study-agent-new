export function downsampleBuffer(
  source: Float32Array,
  sourceRate: number,
  targetRate: number,
): Float32Array {
  if (targetRate <= 0 || sourceRate <= 0 || source.length === 0) {
    return new Float32Array()
  }
  if (sourceRate === targetRate || sourceRate < targetRate) {
    return Float32Array.from(source)
  }

  const ratio = sourceRate / targetRate
  const length = Math.max(1, Math.round(source.length / ratio))
  const result = new Float32Array(length)

  let sourceOffset = 0
  for (let index = 0; index < length; index += 1) {
    const nextOffset = Math.min(source.length, Math.round((index + 1) * ratio))
    const start = Math.min(source.length - 1, Math.round(sourceOffset))
    let accumulator = 0
    let count = 0

    for (let position = start; position < nextOffset; position += 1) {
      accumulator += source[position] ?? 0
      count += 1
    }

    result[index] = count > 0 ? accumulator / count : (source[start] ?? 0)
    sourceOffset = nextOffset
  }

  return result
}
