export function getErrorMessage(error) {
  return error?.response?.data?.detail || error?.response?.data?.message || error?.message || "Request failed.";
}

export function fmtDate(value) {
  if (!value) return "Not recorded";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString();
}

export function fmtNumber(value) {
  if (value === null || value === undefined || value === "") return "0";
  const number = Number(value);
  if (Number.isNaN(number)) return String(value);
  return number.toLocaleString();
}

export function fmtBytes(bytes) {
  const value = Number(bytes || 0);
  if (!value) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const index = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1);
  return `${(value / Math.pow(1024, index)).toFixed(index ? 1 : 0)} ${units[index]}`;
}

export function asArray(value, fallback = []) {
  if (Array.isArray(value)) return value;
  if (Array.isArray(value?.items)) return value.items;
  if (Array.isArray(value?.rows)) return value.rows;
  if (Array.isArray(value?.results)) return value.results;
  return fallback;
}

export function compactId(value) {
  return value ? String(value).slice(0, 8) : "none";
}
