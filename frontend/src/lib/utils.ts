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
  INPUTS_IN_PROGRESS: "输入中",
  OUTLINE_LOCKED: "大纲已锁",
  LITERATURE_READY: "文献已备",
  FETCHING_PAPERS: "同步文献中",
  DRAFTING: "撰写中",
  HAS_DRAFT: "已有草稿",
  // 兼容旧数据
  COMPLETED: "已有草稿",
};

export function statusColor(status: string) {
  switch (status) {
    case "HAS_DRAFT":
    case "COMPLETED":
      return "bg-sky-100 text-sky-800";
    case "LITERATURE_READY":
    case "OUTLINE_LOCKED":
      return "bg-emerald-100 text-emerald-800";
    case "DRAFTING":
    case "FETCHING_PAPERS":
      return "bg-amber-100 text-amber-800";
    case "INPUTS_IN_PROGRESS":
      return "bg-violet-100 text-violet-800";
    default:
      return "bg-stone-100 text-stone-700";
  }
}
