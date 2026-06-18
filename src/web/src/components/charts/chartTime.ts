import type { Time } from "lightweight-charts";

/** UTC calendar day — matches backend daily K-line `date` field. */
export function tsToChartDay(tsSec: number): string {
  const date = new Date(tsSec * 1000);
  const year = date.getUTCFullYear();
  const month = String(date.getUTCMonth() + 1).padStart(2, "0");
  const day = String(date.getUTCDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

export function toChartTime(value?: string | number): Time {
  if (value == null) {
    return "1970-01-01" as Time;
  }
  if (typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value)) {
    return value as Time;
  }
  if (typeof value === "number") {
    return tsToChartDay(value) as Time;
  }
  return value as Time;
}

export function formatChartTimeLabel(time: Time): string {
  if (typeof time === "string") {
    return time;
  }
  if (typeof time === "number") {
    return tsToChartDay(time);
  }
  if (typeof time === "object" && time !== null && "year" in time) {
    const day = time as { year: number; month: number; day: number };
    return `${day.year}-${String(day.month).padStart(2, "0")}-${String(day.day).padStart(2, "0")}`;
  }
  return String(time);
}

export function compareChartTime(left: Time, right: Time): number {
  return formatChartTimeLabel(left).localeCompare(formatChartTimeLabel(right));
}

export const dailyChartLocalization = {
  locale: "zh-CN",
  dateFormat: "yyyy-MM-dd",
  timeFormatter: formatChartTimeLabel,
} as const;
