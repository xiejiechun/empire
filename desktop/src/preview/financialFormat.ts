// Shift and round decimal strings without losing the original integer precision.
export function scaledDecimal(raw: string, shift: number, places?: number): string {
  const match = /^(-?)(\d+)(?:\.(\d+))?$/.exec(raw);
  if (!match) return raw;
  const fraction = match[3] || "";
  let digits = BigInt(match[2] + fraction);
  let scale = fraction.length - shift;
  if (scale < 0) { digits *= 10n ** BigInt(-scale); scale = 0; }
  if (places != null && scale > places) {
    const divisor = 10n ** BigInt(scale - places);
    digits = (digits + divisor / 2n) / divisor;
    scale = places;
  }
  const value = digits.toString().padStart(scale + 1, "0");
  const whole = scale ? value.slice(0, -scale) : value;
  const tail = scale ? value.slice(-scale).replace(/0+$/, "") : "";
  return (digits && match[1] ? "-" : "") + whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",") + (tail ? "." + tail : "");
}

export function financialDisplay(raw: string, format?: string): string | undefined {
  if (format === "clock" && /^\d{6}$/.test(raw)) return raw.replace(/(..)(..)(..)/, "$1:$2:$3");
  if (!/^-?\d+(\.\d+)?$/.test(raw)) return undefined;
  if (format === "percent") return scaledDecimal(raw, 2) + "%";
  if (format === "money") {
    const whole = raw.replace(/^-/, "").split(".")[0].replace(/^0+/, "") || "0";
    const shift = whole.length > 8 ? -8 : whole.length > 4 ? -4 : 0;
    return scaledDecimal(raw, shift, shift ? 2 : undefined) + (shift === -8 ? "亿" : shift === -4 ? "万" : "");
  }
  return undefined;
}
