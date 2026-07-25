import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatDate(iso?: string | null) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export const STATUS_LABELS: Record<string, string> = {
  INITIALIZING: "初始化",
  FETCHING_PAPERS: "检索文献",
  DRAFTING: "撰写中",
  COMPLETED: "已完成",
};

export function statusColor(status: string) {
  switch (status) {
    case "COMPLETED":
      return "bg-emerald-100 text-emerald-800";
    case "DRAFTING":
    case "FETCHING_PAPERS":
      return "bg-amber-100 text-amber-800";
    default:
      return "bg-stone-100 text-stone-700";
  }
}
