export type Json = Record<string, any>;
export async function request<T = Json>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, { ...init, headers: {'Content-Type':'application/json', ...init?.headers} });
  const result = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(result.error?.message || `Request failed (${response.status})`);
  return result as T;
}
export function post<T = Json>(path: string, body: unknown) {return request<T>(path,{method:'POST',body:JSON.stringify(body)});}
export function finite(value: unknown): value is number {return typeof value === 'number' && Number.isFinite(value);}
export function number(value: unknown, digits = 2): string {return finite(value) ? value.toLocaleString('en-US',{maximumFractionDigits:digits}) : '—';}
export function fixed(value: unknown, digits = 3): string {return finite(value) ? value.toFixed(digits) : '—';}
export function percent(value: unknown, digits = 1): string {return finite(value) ? `${(value*100).toFixed(digits)}%` : '—';}

const SUPERSCRIPT: Record<string,string> = {'-':'⁻','0':'⁰','1':'¹','2':'²','3':'³','4':'⁴','5':'⁵','6':'⁶','7':'⁷','8':'⁸','9':'⁹'};
export function powerOfTen(exponent: number): string {return `10${String(exponent).split('').map(c=>SUPERSCRIPT[c]??c).join('')}`;}
/** Probability in scientific notation, e.g. 1.28×10⁻³. */
export function probability(value: unknown, digits = 2): string {
  if (!finite(value)) return '—';
  if (value === 0) return '0';
  if (value >= 0.01) return value.toPrecision(digits + 1);
  const exponent = Math.floor(Math.log10(value));
  const mantissa = value / Math.pow(10, exponent);
  return `${mantissa.toFixed(digits)}×${powerOfTen(exponent)}`;
}
/** Probability from a base-10 logarithm, as stored in the ESA data. */
export function logProbability(value: unknown, digits = 2): string {return finite(value) ? probability(Math.pow(10, value), digits) : '—';}
