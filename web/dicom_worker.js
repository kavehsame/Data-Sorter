self.addEventListener("message", ({ data: bytes }) => {
  try {
    const dicom = self.daikon.Series.parseImage(new DataView(bytes));
    if (!dicom?.getPixelData()) throw new Error("This DICOM has no previewable pixel data.");
    const width = dicom.getCols(), height = dicom.getRows();
    const count = width * height;
    if (!Number.isSafeInteger(count) || count < 1 || count > 24_000_000) throw new Error("Unsupported DICOM frame size.");
    const photo = dicom.getPhotometricInterpretation()?.trim();
    const bits = dicom.getBitsAllocated();
    const stored = dicom.getBitsStored();
    const raw = new DataView(dicom.getPixelDataBytes());
    const result = new Uint8ClampedArray(count * 4);
    if (photo === "MONOCHROME1" || photo === "MONOCHROME2") {
      if (![8, 16, 32].includes(bits) || stored < 1 || stored > bits || raw.byteLength < count * bits / 8) {
        throw new Error("Unsupported DICOM pixel format.");
      }
      const signed = dicom.getPixelRepresentation() === 1;
      const scale = dicom.getDataScaleSlope() || 1, intercept = dicom.getDataScaleIntercept() || 0;
      const values = new Float64Array(count);
      const range = 2 ** stored, sign = range / 2;
      const center = dicom.getWindowCenter(), window = dicom.getWindowWidth();
      const windowed = Number.isFinite(center) && window > 0;
      let low = Infinity, high = -Infinity;
      for (let i = 0; i < count; i += 1) {
        const pixel = bits === 8 ? raw.getUint8(i) : bits === 16 ?
          raw.getUint16(i * 2, dicom.littleEndian) : raw.getUint32(i * 4, dicom.littleEndian);
        const retained = pixel % range;
        let value = scale * (signed && retained >= sign ? retained - range : retained) + intercept;
        if (windowed) value = Math.max(center - window / 2, Math.min(center + window / 2, value));
        values[i] = value;
        low = Math.min(low, value);
        high = Math.max(high, value);
      }
      for (let i = 0; i < count; i += 1) {
        const value = high > low ? (values[i] - low) * 255 / (high - low) : 0;
        result.fill(photo === "MONOCHROME1" ? 255 - value : value, i * 4, i * 4 + 3);
        result[i * 4 + 3] = 255;
      }
    } else {
      const palette = dicom.isPalette();
      const planar = dicom.getPlanarConfig() === 1 && !dicom.isCompressed() && !palette;
      const subsampled = photo === "YBR_FULL_422" && !dicom.isCompressed();
      const ybr = photo?.startsWith("YBR") && !dicom.isCompressed();
      const length = subsampled ? Math.ceil(width / 2) * height * 4 : count * 3;
      if ((!palette && bits !== 8) || raw.byteLength < length || !(palette || photo === "RGB" || photo?.startsWith("YBR"))) {
        throw new Error("Unsupported DICOM colour format.");
      }
      for (let i = 0; i < count; i += 1) {
        const row = Math.floor(i / width), col = i % width;
        const pos = subsampled ? (row * Math.ceil(width / 2) + Math.floor(col / 2)) * 4 : i * 3;
        const a = raw.getUint8(subsampled ? pos + col % 2 : planar ? i : pos);
        const b = raw.getUint8(subsampled ? pos + 2 : planar ? i + count : pos + 1);
        const c = raw.getUint8(subsampled ? pos + 3 : planar ? i + count * 2 : pos + 2);
        result[i * 4] = ybr ? a + 1.402 * (c - 128) : a;
        result[i * 4 + 1] = ybr ? a - 0.344136 * (b - 128) - 0.714136 * (c - 128) : b;
        result[i * 4 + 2] = ybr ? a + 1.772 * (b - 128) : c;
        result[i * 4 + 3] = 255;
      }
    }
    self.postMessage({ width, height, pixels: result }, [result.buffer]);
  } catch (error) {
    self.postMessage({ error: error.message || "The DICOM frame could not be decoded." });
  }
});
