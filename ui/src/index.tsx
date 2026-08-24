import React, { useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Activity,
  AlertTriangle,
  Bell,
  BookOpen,
  Box,
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  CircleUserRound,
  ClipboardList,
  Cpu,
  Database,
  Download,
  Eye,
  EyeOff,
  FileText,
  Gauge,
  Grid2X2,
  Image,
  List,
  Lock,
  LogOut,
  Plus,
  RefreshCw,
  RotateCw,
  Search,
  Trash2,
  X,
} from "lucide-react";
import {
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import "./styles.css";
import { disableLogo, enableLogo, fetchSystemLogo, uploadSystemLogo } from "./api";

type Page = "dashboard" | "resources" | "instances" | "pending" | "ports" | "alerts" | "audit" | "login";
type Lang = "zh" | "en";
type TimeRange = "1h" | "24h" | "7d";

const accent = "#b8f155";
const ink = "#18181b";
const muted = "#7b8494";

const summaryCards = [
  { label: "集群健康", value: "绿色", detail: "3 个节点在线，资源调度正常", icon: Check, progress: 88 },
  { label: "运行卡数", value: "13/14", detail: "GPU/NPU Total", icon: Cpu, progress: 78 },
  { label: "显存利用率", value: "41.3%", detail: "192.0GiB / 464.5GiB", icon: Database, progress: 41 },
  { label: "告警数量", value: "4", detail: "High 2 / Medium 1 / Low 1", icon: Bell, progress: 42, page: "alerts" as Page },
];

const benefitTrend = [
  { name: "13:00", gpu: 55, vram: 48, vgpu: 62, light: 26, main: 51 },
  { name: "14:00", gpu: 49, vram: 44, vgpu: 66, light: 31, main: 48 },
  { name: "15:00", gpu: 62, vram: 58, vgpu: 74, light: 54, main: 64 },
  { name: "16:00", gpu: 46, vram: 42, vgpu: 69, light: 38, main: 52 },
  { name: "17:00", gpu: 56, vram: 53, vgpu: 81, light: 61, main: 58 },
  { name: "18:00", gpu: 50, vram: 47, vgpu: 86, light: 44, main: 63 },
];

const trendDataByRange: Record<TimeRange, typeof benefitTrend> = {
  "1h": benefitTrend,
  "24h": benefitTrend.map((item, index) => ({
    ...item,
    name: `${String(index * 4).padStart(2, "0")}:00`,
    gpu: Math.max(30, item.gpu + (index % 2 ? 8 : -4)),
    vram: Math.max(28, item.vram + (index % 3 ? 6 : -5)),
    main: Math.max(20, item.main + (index % 2 ? 5 : -3)),
  })),
  "7d": benefitTrend.map((item, index) => ({
    ...item,
    name: `D${index + 1}`,
    gpu: Math.max(30, item.gpu + (index % 2 ? -6 : 10)),
    vram: Math.max(28, item.vram + (index % 2 ? -4 : 8)),
    main: Math.max(20, item.main + (index % 3 ? 7 : -6)),
  })),
};

const nodes = [
  { name: "node-gpu-01", status: "绿色", cards: "2 / 2", used: "3.47GiB", total: "42.04GiB", vram: 8.26, type: "GPU", risk: "低" },
  { name: "node-gpu-02", status: "黄色", cards: "3 / 4", used: "56.12GiB", total: "86.48GiB", vram: 64.8, type: "GPU", risk: "中" },
  { name: "node-npu-01", status: "绿色", cards: "6 / 8", used: "132.4GiB", total: "320GiB", vram: 41.3, type: "NPU", risk: "低" },
];

const instances = [
  {
    id: "BD-INF-1024",
    name: "qwen2.5-72b-prod",
    model: "Qwen2.5-72B-Instruct",
    creator: "admin@bluedot.ai",
    spec: "8 x NVIDIA L40S",
    extra: "128 vCPU · 384 GB",
    lifecycle: "已部署",
    runtime: "运行中",
    operation: "空闲",
    perf: "QPS 1860",
    latency: "延迟 286 ms · 首 Token 0.36 s",
    tags: ["高可用部署", "GPU 推理集群"],
    resourceMode: "物理 GPU",
    binding: "SG-01 / GPU-01",
    risk: "低",
  },
  {
    id: "BD-INF-1025",
    name: "deepseek-r1-finance",
    model: "DeepSeek-R1-Distill-32B",
    creator: "ops",
    spec: "4 x NVIDIA A100",
    extra: "96 vCPU · 256 GB",
    lifecycle: "部署中",
    runtime: "排队中",
    operation: "资源检测中",
    perf: "QPS 0",
    latency: "延迟 - · 首 Token -",
    tags: ["标准部署", "GPU 专属资源"],
    resourceMode: "独占 vGPU",
    binding: "node-gpu-03 / vGPU-03-1",
    risk: "中",
  },
  {
    id: "BD-INF-1026",
    name: "llama3-vision-test",
    model: "Llama-3.2-Vision-11B",
    creator: "alice",
    spec: "2 x Ascend 910B",
    extra: "48 vCPU · 128 GB",
    lifecycle: "异常中",
    runtime: "失败",
    operation: "待处理",
    perf: "QPS 0",
    latency: "延迟 - · 首 Token -",
    tags: ["测试部署", "NPU 混合资源"],
    resourceMode: "NPU",
    binding: "node-npu-01",
    risk: "高",
  },
  {
    id: "BD-INF-1027",
    name: "embedding-bge-m3",
    model: "BGE-M3 Embedding",
    creator: "platform",
    spec: "2 x NVIDIA T4",
    extra: "160 vCPU · 192 GB",
    lifecycle: "已部署",
    runtime: "运行中",
    operation: "扩容观察中",
    perf: "QPS 4230",
    latency: "延迟 91 ms · 首 Token 0.12 s",
    tags: ["弹性部署", "CPU + GPU 混合资源"],
    resourceMode: "共享 vGPU",
    binding: "node-gpu-02 / vGPU-02-2",
    risk: "中",
  },
];

const alerts = [
  {
    level: "高",
    category: "镜像拉取失败",
    title: "镜像拉取失败",
    desc: "镜像地址无法访问，实例创建流程已中断。",
    target: "registry.local/infer/nvidia:broken xl",
    time: "41 分钟前",
    action: "切换镜像源或回滚至 latest 可用版本",
  },
  {
    level: "高",
    category: "虚拟化异常",
    title: "vGPU-01-1 资源超限",
    desc: "当前 vGPU 使用率达到 94%，主任务与轻量任务存在资源争抢。",
    target: "node-a310p-01 / GPU-01",
    time: "22 分钟前",
    action: "将轻量任务迁移至 vGPU-03-2，降低峰值重叠",
  },
  {
    level: "中",
    category: "峰值重叠风险",
    title: "node-gpu-02 显存偏高",
    desc: "显存利用率已达到 64.8%，建议关注后续增长趋势。",
    target: "node-gpu-02 alice",
    time: "18 分钟前",
    action: "观察 24 小时曲线，必要时排队新任务",
  },
  {
    level: "低",
    category: "端口冲突",
    title: "端口即将达到预警阈值",
    desc: "当前端口白名单记录 3 个，建议定期清理无效记录。",
    target: "port-list system",
    time: "31 分钟前",
    action: "清理长期未使用的端口白名单记录",
  },
];

const audits = [
  ["system", "添加模拟数据", "nvidia-cuda-bd3498", "成功", "2026-05-13 13:14:38"],
  ["admin", "虚拟卡推荐", "node-gpu-03 / vGPU-03-1", "成功", "2026-05-13 13:13:02"],
  ["admin", "实例进入高优先级排队", "deepseek-r1-finance", "通过", "2026-05-13 12:58:46"],
  ["ops", "策略分析", "峰值重叠风险", "成功", "2026-05-13 12:44:11"],
  ["admin", "告警处理", "vGPU-01-1 资源超限", "成功", "2026-05-13 12:04:17"],
  ["system", "资源预检", "NVIDIA/GPU x 1", "通过", "2026-05-12 10:49:02"],
  ["admin", "镜像查询", "nvidia-cuda-a8f21c", "失败", "2026-05-12 10:42:55"],
];

const drafts = [
  { name: "nvidia-cuda-auto-001", meta: "NvidiaInfer · GPU x 1 / Port 8018 · 2026-05-13 13:15:23", resource: "NVIDIA/GPU", gpu: 1 },
  { name: "nvidia-cuda-draft-8022", meta: "NvidiaInfer · GPU x 2 / 端口 8022 · 2026-05-12 11:26:00", resource: "NVIDIA/GPU", gpu: 2 },
];

const ports = [
  { id: "222c6a67", port: "55055", usage: "grpc", creator: "ops", date: "2026-04-03 17:09:24" },
  { id: "2c8004b2", port: "50056", usage: "web api", creator: "admin", date: "2026-05-12 10:51:28" },
];

const closedPorts = [
  { port: "50055", name: "web api", person: "alice", time: "2026-04-03 17:11:22" },
  { port: "55055", name: "grpc", person: "ops", time: "2026-04-03 17:09:24" },
  { port: "50056", name: "web api", person: "alice", time: "2026-05-12 10:51:28" },
];

const strategyModes = [
  {
    mode: "轻量共享虚拟卡",
    usage: "1.2 - 2.6 vGPU",
    split: "40% + 40% + 20%预留",
    risk: "低，需监控峰值重叠",
  },
  {
    mode: "高优先级排队",
    usage: "2.4 - 4.0 vGPU",
    split: "60%主任务 + 30%弹性 + 10%预留",
    risk: "中，优先调度但需观察峰值",
  },
  {
    mode: "显存保护模式",
    usage: "1.0 - 1.8 vGPU",
    split: "30%计算 + 30%显存 + 40%预留",
    risk: "低，适合显存敏感任务",
  },
  {
    mode: "峰值错峰迁移",
    usage: "1.6 - 3.2 vGPU",
    split: "50%运行 + 30%迁移 + 20%预留",
    risk: "中，建议避开资源峰值窗口",
  },
];

const gpuResourceGauges = [
  { label: "vGPU 分配率", value: 72, detail: "20 / 28 vGPU" },
  { label: "算力分配率", value: 68, detail: "438 / 640 TFLOPS" },
  { label: "显存分配率", value: 61, detail: "390 / 640 GiB" },
  { label: "算力使用率", value: 54, detail: "346 / 640 TFLOPS" },
  { label: "显存使用率", value: 47, detail: "301 / 640 GiB" },
];

const resourceOverview = [
  { label: "节点", value: "5", unit: "个" },
  { label: "显卡", value: "14", unit: "张" },
  { label: "vGPU", value: "28", unit: "个" },
  { label: "算力", value: "640", unit: "TFLOPS" },
  { label: "显存大小", value: "640", unit: "GiB" },
];

const gpuTypeData = [
  { name: "NVIDIA A100", value: 4, color: "#b8f155" },
  { name: "NVIDIA L40S", value: 3, color: "#1f2937" },
  { name: "NVIDIA T4", value: 3, color: "#8b5cf6" },
  { name: "Ascend 910B", value: 2, color: "#ef4444" },
  { name: "Ascend 310P", value: 2, color: "#f59e0b" },
];

const nodeAllocationTop5 = [
  { name: "node-gpu-02", value: 86 },
  { name: "node-a310p-01", value: 78 },
  { name: "node-gpu-03", value: 71 },
  { name: "node-gpu-01", value: 64 },
  { name: "node-npu-01", value: 58 },
];

const gpuInventory = [
  { id: "GPU-node-gpu-02-01", status: "高负载", mode: "vGPU 后台调度", node: "node-gpu-02", model: "NVIDIA A100", vgpu: "2 / 2", compute: "88 / 100", memory: "62 / 80 GiB" },
  { id: "GPU-node-gpu-02-02", status: "运行中", mode: "vGPU 后台调度", node: "node-gpu-02", model: "NVIDIA A100", vgpu: "2 / 2", compute: "74 / 100", memory: "55 / 80 GiB" },
  { id: "GPU-node-gpu-03-01", status: "运行中", mode: "vGPU 后台调度", node: "node-gpu-03", model: "NVIDIA L40S", vgpu: "1 / 2", compute: "44 / 80", memory: "31 / 48 GiB" },
  { id: "GPU-node-gpu-01-01", status: "空闲", mode: "vGPU 后台调度", node: "node-gpu-01", model: "NVIDIA T4", vgpu: "0 / 2", compute: "12 / 65", memory: "8 / 32 GiB" },
  { id: "GPU-node-a310p-01-01", status: "运行中", mode: "vGPU 后台调度", node: "node-a310p-01", model: "Ascend 310P", vgpu: "2 / 2", compute: "68 / 90", memory: "44 / 64 GiB" },
];

const vgpuGuideSteps = [
  { label: "接入显卡资源池", title: "14 张 GPU", detail: "A100 / L40S / T4 / Ascend", foot: "仅作为后台资源池基础单元" },
  { label: "统一 vGPU 池", title: "28 个 vGPU", detail: "1 GPU = 2 vGPU", foot: "实例不直接选择物理卡" },
  { label: "资源配额层", title: "算力 + 显存", detail: "按任务预测占用动态分配", foot: "分配率与使用率独立统计" },
  { label: "任务队列", title: "优先级调度", detail: "高优先级任务排队时优先处理", foot: "资源不足先排队再保存待发布" },
  { label: "实例运行", title: "后台绑定", detail: "系统自动完成 vGPU 绑定与迁移", foot: "前台仅展示模式与风险" },
];

const loginSlides = [
  {
    eyebrow: "vGPU 后台调度",
    title: "统一资源池，不再手动拆卡",
    desc: "所有接入 GPU 统一进入 vGPU 调度池，前台只关注推荐模式、预测占用与风险。",
    mode: "pool",
  },
  {
    eyebrow: "资源与告警联动",
    title: "从创建到运行都可预检",
    desc: "GPU、显存、端口、配额与镜像检查前置，资源不足优先进入队列并保留审计线索。",
    mode: "precheck",
  },
  {
    eyebrow: "运维驾驶舱",
    title: "趋势、实例、风险一屏闭环",
    desc: "资源趋势、节点显存采集、实时告警与推荐策略协同呈现，方便快速定位容量瓶颈。",
    mode: "dashboard",
  },
];

function cx(...items: Array<string | false | undefined>) {
  return items.filter(Boolean).join(" ");
}

function StatusBadge({ value }: { value: string }) {
  const tone = value.includes("失败") || value.includes("异常") || value.includes("高")
    ? "red"
    : value.includes("排队") || value.includes("部署") || value.includes("检测") || value.includes("中")
      ? "amber"
      : value.includes("扩容")
        ? "blue"
        : value.includes("已停止")
          ? "gray"
          : "green";
  return <span className={`badge ${tone}`}>{value}</span>;
}

function App() {
  const [page, setPage] = useState<Page>("login");
  const [lang, setLang] = useState<Lang>("zh");
  const [accountOpen, setAccountOpen] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [activeInstance, setActiveInstance] = useState("BD-INF-1024");
  const [range, setRange] = useState<TimeRange>("1h");
  const [resourceTab, setResourceTab] = useState<"topology" | "curve" | "policy">("topology");
  const [alertFilter, setAlertFilter] = useState("全部层级");
  const [guideOpen, setGuideOpen] = useState(() => window.localStorage.getItem("bluedot-vgpu-guide-read") !== "1");
  const [loggedIn, setLoggedIn] = useState(false);
  const [mockToast, setMockToast] = useState("");
  const [logoUrl, setLogoUrl] = useState("");
  const [logoEnabled, setLogoEnabled] = useState(false);
  const [logoModalOpen, setLogoModalOpen] = useState(false);

  useEffect(() => {
    fetchSystemLogo().then((data) => {
      if (data.logo_url && data.logo_enabled) {
        setLogoUrl(data.logo_url);
        setLogoEnabled(true);
      }
    }).catch(() => {});
  }, []);

  const handleEnableLogo = async () => {
    try {
      const result = await enableLogo();
      setLogoUrl(result.logo_url);
      setLogoEnabled(true);
    } catch { /* backend will show error via toast if needed */ }
  };

  const handleDisableLogo = async () => {
    try {
      await disableLogo();
      setLogoUrl("");
      setLogoEnabled(false);
    } catch { /* backend will show error via toast if needed */ }
  };

  const closeGuide = () => {
    window.localStorage.setItem("bluedot-vgpu-guide-read", "1");
    setGuideOpen(false);
  };

  const addMockData = () => {
    setMockToast("已添加 1 组虚拟资源、实例与告警数据");
    window.setTimeout(() => setMockToast(""), 2600);
  };

  useEffect(() => {
    const selector = [
      ".content .metric-card",
      ".content .card",
      ".content .policy-card",
      ".content .category",
      ".content .filter-card",
    ].join(", ");
    const modules = Array.from(document.querySelectorAll<HTMLElement>(selector));

    if (!("IntersectionObserver" in window)) {
      modules.forEach((module) => module.classList.add("is-visible"));
      return;
    }

    modules.forEach((module, index) => {
      module.classList.add("reveal-on-scroll");
      module.style.setProperty("--reveal-delay", `${Math.min(index * 35, 180)}ms`);
    });

    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            entry.target.classList.add("is-visible");
            observer.unobserve(entry.target);
          }
        });
      },
      {
        threshold: 0.12,
        rootMargin: "0px 0px -8% 0px",
      },
    );

    modules.forEach((module) => observer.observe(module));
    return () => observer.disconnect();
  }, [page, activeInstance, resourceTab, alertFilter]);

  const pageTitle = useMemo(() => {
    const map: Record<Page, string> = {
      dashboard: "AI 算力资源管理端",
      resources: "资源中心",
      instances: "实例中心",
      pending: "待发布",
      ports: "端口白名单",
      alerts: "告警中心",
      audit: "审计日志",
      login: "登录",
    };
    return map[page];
  }, [page]);

  if (page === "login") {
    return (
      <>
        <style>{styles}</style>
        <LoginPage
          logoUrl={logoUrl}
          onLogin={() => {
            setLoggedIn(true);
            setPage("dashboard");
          }}
        />
      </>
    );
  }

  return (
    <>
      <style>{styles}</style>
      <div className="app-shell">
        <Sidebar page={page} setPage={setPage} onGuideOpen={() => setGuideOpen(true)} logoUrl={logoUrl} />
        <main className="main">
          <Topbar
            title={pageTitle}
            lang={lang}
            setLang={setLang}
            setPage={setPage}
            accountOpen={accountOpen}
            setAccountOpen={setAccountOpen}
            loggedIn={loggedIn}
            onLogin={() => setPage("login")}
            onLogout={() => {
              setLoggedIn(false);
              setAccountOpen(false);
              setPage("login");
            }}
            onAddMockData={addMockData}
            onCreate={() => setCreateOpen(true)}
            onOpenLogoModal={() => setLogoModalOpen(true)}
            logoEnabled={logoEnabled}
            onEnableLogo={handleEnableLogo}
            onDisableLogo={handleDisableLogo}
          />
          <div className="content">
            {page === "dashboard" && <Dashboard setPage={setPage} onCreate={() => setCreateOpen(true)} />}
            {page === "resources" && <Resources tab={resourceTab} setTab={setResourceTab} range={range} setRange={setRange} />}
            {page === "instances" && (
              <Instances activeInstance={activeInstance} setActiveInstance={setActiveInstance} onCreate={() => setCreateOpen(true)} />
            )}
            {page === "pending" && <Pending onCreate={() => setCreateOpen(true)} />}
            {page === "ports" && <Ports />}
            {page === "alerts" && <Alerts filter={alertFilter} setFilter={setAlertFilter} />}
            {page === "audit" && <Audit />}
          </div>
        </main>
      </div>
      {createOpen && <CreateModal onClose={() => setCreateOpen(false)} />}
      {guideOpen && <VgpuGuideOverlay onClose={closeGuide} />}
      {mockToast && <div className="toast">{mockToast}</div>}
      {logoModalOpen && (
        <LogoUploadModal
          onClose={() => setLogoModalOpen(false)}
          onUploaded={(url: string) => { setLogoUrl(url); setLogoEnabled(true); setLogoModalOpen(false); }}
        />
      )}
    </>
  );
}

function Sidebar({ page, setPage, onGuideOpen, logoUrl }: { page: Page; setPage: (page: Page) => void; onGuideOpen: () => void; logoUrl: string }) {
  const links = [
    { id: "dashboard" as Page, label: "首页", icon: Grid2X2 },
    { id: "resources" as Page, label: "资源中心", icon: Cpu },
    { id: "instances" as Page, label: "实例中心", icon: Box, children: ["推理与部署", "待发布"] },
    { id: "ports" as Page, label: "端口白名单", icon: Lock },
    { id: "alerts" as Page, label: "告警中心", icon: AlertTriangle },
    { id: "audit" as Page, label: "审计日志", icon: ClipboardList },
  ];

  return (
    <aside className="sidebar">
      <div className="brand">
        {logoUrl ? (
          <img className="brand-mark-img" src={logoUrl} alt="BlueDot" />
        ) : (
          <div className="brand-mark">B</div>
        )}
        <div>
          <strong>BlueDot</strong>
          <span>INTELLIGENCE</span>
        </div>
      </div>
      <nav className="nav">
        {links.map((link) => {
          const Icon = link.icon;
          const active = page === link.id || (link.id === "instances" && page === "pending");
          return (
            <div key={link.id}>
              <button className={cx("nav-item", active && "active")} onClick={() => setPage(link.id)}>
                <Icon size={17} />
                <span>{link.label}</span>
                {link.id === "alerts" && <i className="nav-dot" />}
              </button>
              {link.children && active && (
                <div className="subnav">
                  <button className={page === "instances" ? "sub-active" : ""} onClick={() => setPage("instances")}>
                    推理与部署
                  </button>
                  <button className={page === "pending" ? "sub-active" : ""} onClick={() => setPage("pending")}>
                    待发布
                  </button>
                </div>
              )}
            </div>
          );
        })}
      </nav>
      <div className="sidebar-bottom">
        <div className="health-card">
          <div className="pill">GPU 虚拟化健康分</div>
          <strong>86</strong>
          <p>2 张卡存在峰值重叠风险</p>
        </div>
        <button className="guide-card" onClick={onGuideOpen}>
          <span>新手引导</span>
          <p>5 步理解显卡资源池、队列与实例绑定</p>
          <i><ChevronRight size={16} /></i>
        </button>
        <p className="copyright">Copyright (c) BlueDot. All Rights Reserved</p>
      </div>
    </aside>
  );
}

function Topbar({
  title,
  lang,
  setLang,
  setPage,
  accountOpen,
  setAccountOpen,
  loggedIn,
  onLogin,
  onLogout,
  onAddMockData,
  onCreate,
  onOpenLogoModal,
  logoEnabled,
  onEnableLogo,
  onDisableLogo,
}: {
  title: string;
  lang: Lang;
  setLang: (lang: Lang) => void;
  setPage: (page: Page) => void;
  accountOpen: boolean;
  setAccountOpen: (open: boolean) => void;
  loggedIn: boolean;
  onLogin: () => void;
  onLogout: () => void;
  onAddMockData: () => void;
  onCreate: () => void;
  onOpenLogoModal: () => void;
  logoEnabled: boolean;
  onEnableLogo: () => void;
  onDisableLogo: () => void;
}) {
  return (
    <header className="topbar">
      <div className="topbar-inner">
        <div className="title-block">
          <h1>{title}</h1>
        </div>
        <label className="search">
          <Search size={18} />
          <input placeholder="搜索实例、节点、端口、告警" />
        </label>
        <div className="lang-switch">
          <button className={lang === "zh" ? "selected" : ""} onClick={() => setLang("zh")}>中</button>
          <button className={lang === "en" ? "selected" : ""} onClick={() => setLang("en")}>EN</button>
        </div>
        <button className="ghost" onClick={onAddMockData}><Plus size={16} />添加虚拟数据</button>
        <button className="primary" onClick={onCreate}><Plus size={17} />创建实例</button>
        <div className="account-wrap">
          {loggedIn ? (
            <button className="account" onClick={() => setAccountOpen(!accountOpen)}>
              <CircleUserRound size={17} /> admin <ChevronDown size={15} />
            </button>
          ) : (
            <button className="account login-entry" onClick={onLogin}>登录</button>
          )}
          {loggedIn && accountOpen && (
            <div className="account-menu">
              <small>账号</small>
              <strong>admin</strong>
              <hr />
              <button onClick={() => { setAccountOpen(false); onOpenLogoModal(); }}><Image size={16} /> 更换Logo</button>
              {logoEnabled && (
                <button onClick={() => { setAccountOpen(false); onDisableLogo(); }}><RotateCw size={16} /> 恢复默认Logo</button>
              )}
              <button><RotateCw size={16} /> 切换账号</button>
              <button className="danger" onClick={onLogout}><LogOut size={16} /> 退出</button>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}

function LoginPage({ onLogin, logoUrl }: { onLogin: () => void; logoUrl: string }) {
  const [slideIndex, setSlideIndex] = useState(0);
  const [showPassword, setShowPassword] = useState(false);
  const [account, setAccount] = useState("");
  const [password, setPassword] = useState("");
  const slide = loginSlides[slideIndex];
  const canSubmit = account.trim().length > 0 && password.length > 0;

  useEffect(() => {
    const timer = window.setInterval(() => {
      setSlideIndex((current) => (current + 1) % loginSlides.length);
    }, 5000);
    return () => window.clearInterval(timer);
  }, []);

  return (
    <main className="login-page">
      <section className="login-shell">
        <div className="login-form-panel">
          <div className="login-wordmark">BlueDot</div>
          {logoUrl ? (
            <img className="login-brand-mark-img" src={logoUrl} alt="BlueDot" />
          ) : (
            <div className="login-brand-mark">B</div>
          )}
          <div className="login-copy">
            <h1>登录</h1>
            <p>企业 AI 推理场景的 GPU/NPU 资源监控、虚拟化资源调度、推理实例部署、运行治理与资源复用优化平台</p>
          </div>
          <div className="login-divider" />
          <form
            className="login-form"
            onSubmit={(event) => {
              event.preventDefault();
              if (canSubmit) onLogin();
            }}
          >
            <label>
              账号
              <input
                type="text"
                value={account}
                onChange={(event) => setAccount(event.target.value)}
                placeholder="请输入账号"
                autoComplete="username"
              />
            </label>
            <label>
              <span>密码 <button type="button">忘记密码?</button></span>
              <div className="password-field">
                <input
                  type={showPassword ? "text" : "password"}
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  placeholder="请输入密码"
                  autoComplete="current-password"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword((visible) => !visible)}
                  aria-label={showPassword ? "隐藏密码" : "显示密码"}
                >
                  {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
                </button>
              </div>
            </label>
            <button className="login-submit" type="submit" disabled={!canSubmit}>登录</button>
          </form>
          <p className="login-footnote">Copyright (c) BlueDot. All Rights Reserved</p>
        </div>

        <div className="login-showcase">
          <div className="login-slide" key={slide.title}>
            <span>{slide.eyebrow}</span>
            <h2>{slide.title}</h2>
            <p>{slide.desc}</p>
          </div>
          <LoginPreview mode={slide.mode} />
          <div className="login-dots">
            {loginSlides.map((item, index) => (
              <button
                key={item.eyebrow}
                className={index === slideIndex ? "active" : ""}
                onClick={() => setSlideIndex(index)}
                aria-label={`查看${item.eyebrow}`}
              />
            ))}
          </div>
        </div>
      </section>
    </main>
  );
}

function LoginPreview({ mode }: { mode: string }) {
  if (mode === "precheck") {
    return (
      <div className="login-preview preview-precheck">
        <div className="preview-top"><b>创建实例</b><i>预检</i></div>
        <div className="precheck-mini-list">
          {["GPU 数量满足", "显存容量满足", "端口未冲突", "镜像地址可访问"].map((item) => (
            <div key={item}><Check size={15} /><span>{item}</span><b>通过</b></div>
          ))}
        </div>
        <div className="preview-row"><strong>资源不足兜底</strong><span>高优先级排队</span></div>
      </div>
    );
  }

  if (mode === "dashboard") {
    return (
      <div className="login-preview preview-dashboard">
        <div className="preview-top"><b>运维驾驶舱</b><i>实时</i></div>
        <div className="preview-chart rich"><i /><i /><i /><i /></div>
        <div className="mini-alert-row"><AlertTriangle size={16} /><strong>node-gpu-02 显存偏高</strong><span>18 分钟前</span></div>
        <div className="preview-row"><strong>资源推荐策略</strong><span>1.2 - 2.6 vGPU</span></div>
      </div>
    );
  }

  return (
    <div className="login-preview preview-pool">
      <div className="preview-top"><b>AI 算力资源管理端</b><i>vGPU</i></div>
      <div className="preview-grid">
        <div><span>显卡</span><strong>14</strong></div>
        <div><span>vGPU</span><strong>28</strong></div>
        <div><span>分配率</span><strong>72%</strong></div>
      </div>
      <div className="preview-pool-flow">
        <span>GPU</span><ChevronRight size={15} /><span>vGPU</span><ChevronRight size={15} /><span>实例</span>
      </div>
      <div className="preview-row"><strong>后台绑定</strong><span>自动调度</span></div>
    </div>
  );
}

function Dashboard({ setPage, onCreate: _onCreate }: { setPage: (page: Page) => void; onCreate: () => void }) {
  const [instanceView, setInstanceView] = useState<"grid" | "list">("grid");
  const [trendRange, setTrendRange] = useState<TimeRange>("1h");
  const trendData = trendDataByRange[trendRange];
  return (
    <section className="page-stack">
      <div className="summary-grid">
        {summaryCards.map((card) => {
          const Icon = card.icon;
          return (
            <button className="metric-card" key={card.label} onClick={() => card.page && setPage(card.page)}>
              <span>{card.label}</span>
              <strong>{card.value}</strong>
              <p>{card.detail}</p>
              <Icon className="metric-icon" size={24} />
              <div className="progress"><i style={{ width: `${card.progress}%` }} /></div>
            </button>
          );
        })}
      </div>

      <div className="dashboard-grid">
        <section className="card chart-card">
          <div className="card-head">
            <div>
              <h2>资源趋势</h2>
              <p>GPU 使用、显存使用与实例数量变化</p>
            </div>
            <div className="segmented">
              {(["1h", "24h", "7d"] as TimeRange[]).map((item) => (
                <button key={item} className={trendRange === item ? "active" : ""} onClick={() => setTrendRange(item)}>
                  {item === "1h" ? "近1小时" : item === "24h" ? "24小时" : "7天"}
                </button>
              ))}
            </div>
          </div>
          <div className="trend-chart-frame" key={trendRange}>
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={trendData}>
              <defs>
                <linearGradient id="limeFill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor={accent} stopOpacity={0.55} />
                  <stop offset="95%" stopColor={accent} stopOpacity={0.02} />
                </linearGradient>
              </defs>
              <CartesianGrid stroke="#edf0f3" vertical={false} />
              <XAxis dataKey="name" tickLine={false} axisLine={false} />
              <YAxis hide domain={[0, 100]} />
              <Tooltip />
              <Line type="monotone" dataKey="gpu" name="GPU 使用" stroke="#111827" strokeWidth={3} dot={false} />
              <Line type="monotone" dataKey="vram" name="显存使用" stroke={accent} strokeWidth={3} dot={false} />
              <Line type="monotone" dataKey="main" name="实例数量" stroke="#7c3aed" strokeWidth={3} dot={{ r: 4 }} />
            </LineChart>
          </ResponsiveContainer>
          </div>
          <div className="legend"><span><i />GPU 使用</span><span><i className="green-dot" />显存使用</span><span><i style={{ background: "#7c3aed" }} />实例数量</span></div>
        </section>

        <NodeVramCollection />
      </div>

      <section className="card instance-overview">
        <div className="card-head">
          <div><h2>部署实例管理</h2><p>查看推理实例状态、资源申请、NodePort 与常用运维操作</p></div>
          <div className="header-actions">
            <button className="ghost compact" onClick={() => setPage("instances")}>查看全部</button>
            <div className="segmented icon-switch">
              <button className={instanceView === "grid" ? "active" : ""} onClick={() => setInstanceView("grid")}><Grid2X2 size={15} /></button>
              <button className={instanceView === "list" ? "active" : ""} onClick={() => setInstanceView("list")}><List size={15} /></button>
            </div>
          </div>
        </div>
        <div className={instanceView === "grid" ? "mini-instance-grid two-rows" : "mini-instance-list"}>
          {instances.map((item) => (
            <div className="mini-instance" key={item.id}>
              <strong>{item.name}</strong>
              <StatusBadge value={item.runtime} />
              <span>{item.spec.split(" x ")[1] ? `GPU: ${item.spec.split(" x ")[0]} · NVIDIA/GPU` : item.spec}</span>
              <div><small>自动调度</small><small>{item.id === "BD-INF-1027" ? "2h 18m" : "6h 00m"}</small></div>
            </div>
          ))}
        </div>
      </section>

      <div className="dashboard-grid bottom three">
        <AlertsCompact setPage={setPage} />
        <ClosedPortList setPage={setPage} />
        <ResourceStrategy setPage={setPage} />
      </div>
    </section>
  );
}

function NodeVramCollection() {
  const [collectedAt, setCollectedAt] = useState("2026-05-12 14:20:00");
  const refresh = () => {
    const now = new Date();
    const pad = (value: number) => String(value).padStart(2, "0");
    setCollectedAt(`${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())} ${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`);
  };

  useEffect(() => {
    const timer = window.setInterval(refresh, 5 * 60 * 1000);
    return () => window.clearInterval(timer);
  }, []);

  return (
    <section className="card node-vram-card">
      <div className="card-head">
        <div><h2>节点显存采集明细</h2><p>采集时间：{collectedAt}</p></div>
        <button className="ghost" onClick={refresh}><RefreshCw size={16} />重新采集</button>
      </div>
      <div className="node-vram-list">
        {nodes.map((node) => (
          <div className="node-vram-row" key={node.name}>
            <div className="node-head">
              <strong>{node.name}</strong>
              <StatusBadge value={node.status} />
            </div>
            <div className="progress"><i style={{ width: `${node.vram}%`, background: node.status === "黄色" ? "#f97316" : "#8bd52d" }} /></div>
            <p>{node.used} / {node.total} · 运行卡数 {node.cards}</p>
          </div>
        ))}
      </div>
    </section>
  );
}

function ResourceStrategy({ setPage }: { setPage: (page: Page) => void }) {
  const [modeIndex, setModeIndex] = useState(0);
  const activeMode = strategyModes[modeIndex];
  const stepMode = (direction: 1 | -1) => {
    setModeIndex((current) => (current + direction + strategyModes.length) % strategyModes.length);
  };

  useEffect(() => {
    const timer = window.setInterval(() => stepMode(1), 10000);
    return () => window.clearInterval(timer);
  }, []);

  return (
    <section className="card strategy-card">
      <div className="card-head">
        <div>
          <h2>资源推荐策略</h2>
          <p>根据历史峰值、任务类型与安全余量推荐</p>
        </div>
        <span className="auto">自动推荐</span>
      </div>
      <div className="strategy-mode-panel" key={activeMode.mode}>
        <InfoRow label="推荐模式" value={activeMode.mode} />
        <InfoRow label="预计占用" value={activeMode.usage} />
        <InfoRow label="推荐切分" value={activeMode.split} />
        <InfoRow label="风险等级" value={activeMode.risk} />
      </div>
      <div className="actions-row strategy-actions">
        <button className="primary compact" onClick={() => setPage("resources")}>查看虚拟资源</button>
        <button className="ghost compact" onClick={() => setPage("alerts")}>查看风险</button>
        <div className="strategy-nav">
          <button className="ghost compact icon-only" aria-label="上一个推荐模式" onClick={() => stepMode(-1)}>
            <ChevronLeft size={16} />
          </button>
          <button className="ghost compact icon-only" aria-label="下一个推荐模式" onClick={() => stepMode(1)}>
            <ChevronRight size={16} />
          </button>
        </div>
      </div>
    </section>
  );
}

function ClosedPortList({ setPage }: { setPage: (page: Page) => void }) {
  return (
    <section className="card closed-ports-card">
      <div className="card-head">
        <div>
          <h2>端口白名单列表</h2>
          <p>端口会参与资源预检，避免 NodePort 冲突</p>
        </div>
        <button className="ghost compact" onClick={() => setPage("ports")}>查看更多</button>
      </div>
      <div className="closed-port-list">
        {closedPorts.map((port) => (
          <div className="closed-port-row" key={`${port.port}-${port.time}`}>
            <strong>{port.port} · {port.name}</strong>
            <div className="closed-port-meta">
              <span>{port.person} · {port.time}</span>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

function Resources({
  tab: _tab,
  setTab: _setTab,
  range: _range,
  setRange: _setRange,
}: {
  tab: "topology" | "curve" | "policy";
  setTab: (tab: "topology" | "curve" | "policy") => void;
  range: TimeRange;
  setRange: (range: TimeRange) => void;
}) {
  const [resourceRefreshedAt, setResourceRefreshedAt] = useState("2026-05-18 14:12:00");
  const [resourceRefreshing, setResourceRefreshing] = useState(false);
  const [resourceAnimationRun, setResourceAnimationRun] = useState(0);
  const refreshResourceCards = () => {
    const now = new Date();
    const pad = (value: number) => String(value).padStart(2, "0");
    setResourceRefreshedAt(`${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())} ${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`);
    setResourceRefreshing(true);
    setResourceAnimationRun((current) => current + 1);
    window.setTimeout(() => setResourceRefreshing(false), 1800);
  };
  return (
    <section className="page-stack">
      <section className="card gpu-gauges">
        <div className="card-head">
          <div><h2>显卡资源</h2><p>最近刷新时间：{resourceRefreshedAt}</p></div>
          <button className="ghost compact" onClick={refreshResourceCards}><RefreshCw size={16} />刷新</button>
        </div>
        <div className="gauge-grid">
          {gpuResourceGauges.map((item, index) => (
            <div className={cx("gauge-card", resourceRefreshing && "is-updating")} style={{ "--stagger": `${index * 100}ms` } as React.CSSProperties} key={item.label}>
              <div className="gauge-card-top">
                <div><Cpu size={16} /><strong>{item.label}</strong></div>
                <button aria-label={`查看${item.label}`}><ChevronRight size={15} /></button>
              </div>
              <p>{item.detail}</p>
              <div className="gauge-value"><AnimatedNumber value={item.value} suffix="%" run={resourceAnimationRun} delay={index * 100} /> <i className={index === 3 ? "warn" : ""} /></div>
              <div className="bar-spark" aria-hidden="true">
                {Array.from({ length: 32 }).map((_, barIndex) => (
                  <span
                    key={`${item.label}-${barIndex}`}
                    className={barIndex < Math.round(item.value / 3.125) ? (index === 3 ? "warn" : "active") : ""}
                  />
                ))}
              </div>
              <div className="gauge-foot"><span>已使用</span><span>剩余</span></div>
            </div>
          ))}
        </div>
      </section>

      <section className="card overview-card">
        <div className="card-head"><div><h2>资源概览</h2><p>统一资源池容量</p></div></div>
        <div className="overview-grid">
          {resourceOverview.map((item) => (
            <div className="overview-item" key={item.label}>
              <span>{item.label}</span>
              <strong>{item.value}</strong>
              <small>{item.unit}</small>
            </div>
          ))}
        </div>
      </section>

      <div className="resource-analytics">
        <section className="card">
          <div className="card-head"><div><h2>显卡类别占比</h2><p>按接入显卡型号统计</p></div></div>
          <div className="pie-panel">
            <ResponsiveContainer width="100%" height={260}>
              <PieChart>
                <Pie data={gpuTypeData} dataKey="value" nameKey="name" innerRadius={58} outerRadius={96} paddingAngle={4}>
                  {gpuTypeData.map((entry) => <Cell key={entry.name} fill={entry.color} />)}
                </Pie>
                <Tooltip />
              </PieChart>
            </ResponsiveContainer>
            <div className="pie-legend">
              {gpuTypeData.map((item) => (
                <span key={item.name}><i style={{ background: item.color }} />{item.name} · {item.value} 张</span>
              ))}
            </div>
          </div>
        </section>

        <section className="card">
          <div className="card-head"><div><h2>节点资源分配率 Top5</h2><p>按 vGPU 与算力综合分配率排序</p></div></div>
          <div className="top5-list">
            {nodeAllocationTop5.map((item, index) => (
              <div className="top5-row" key={item.name}>
                <b>{String(index + 1).padStart(2, "0")}</b>
                <span>{item.name}</span>
                <div className="progress"><i style={{ width: `${item.value}%` }} /></div>
                <strong>{item.value}%</strong>
              </div>
            ))}
          </div>
        </section>
      </div>

      <section className="card gpu-table-card">
        <div className="card-head">
          <div><h2>显卡信息列表</h2><p>物理显卡仅作为后台资源池基础单元展示，实例不直接绑定具体显卡。</p></div>
          <span className="auto">1 GPU = 2 vGPU</span>
        </div>
        <table>
          <thead>
            <tr>
              <th>显卡 ID</th>
              <th>显卡状态</th>
              <th>使用模式</th>
              <th>所属节点</th>
              <th>显卡型号</th>
              <th>vGPU</th>
              <th>算力(已分配/总量)</th>
              <th>显存(已分配/总量)</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {gpuInventory.map((gpu) => (
              <tr key={gpu.id}>
                <td><code>{gpu.id}</code></td>
                <td><StatusBadge value={gpu.status} /></td>
                <td>{gpu.mode}</td>
                <td>{gpu.node}</td>
                <td>{gpu.model}</td>
                <td>{gpu.vgpu}</td>
                <td>{gpu.compute}</td>
                <td>{gpu.memory}</td>
                <td><button className="ghost compact">查看</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </section>
  );
}

function Topology() {
  return (
    <div className="topology">
      <TopoCard label="节点" title="node-a310p-01" lines={["可调度", "节点健康 98%"]} />
      <ChevronRight className="topo-arrow" />
      <TopoCard label="物理 GPU" title="GPU-01 / Ascend 310P" lines={["40% · 40% · 20%预留", "整卡产出提升 +40%"]} bar />
      <ChevronRight className="topo-arrow" />
      <TopoCard label="vGPU 资源单元" title="vGPU-01-1 超限" lines={["vGPU-01-2 正常", "vGPU 使用率 94%"]} warning />
      <ChevronRight className="topo-arrow" />
      <TopoCard label="绑定实例" title="detect-main-prod" lines={["主检测任务 · Running", "detect-light-02 · 轻量任务"]} />
      <ChevronRight className="topo-arrow" />
      <TopoCard label="当前负载" title="GPU 86%" lines={["显存 62%", "vGPU 94%"]} warning />
    </div>
  );
}

function VgpuGuideOverlay({ onClose }: { onClose: () => void }) {
  const [activeStep, setActiveStep] = useState(0);
  const step = vgpuGuideSteps[activeStep];
  const lastStep = activeStep === vgpuGuideSteps.length - 1;
  return (
    <div className="guide-overlay" role="dialog" aria-modal="true" aria-labelledby="vgpu-guide-title">
      <div className="guide-stack" aria-hidden="true" />
      <section className="guide-panel">
        <header className="guide-progress">
          <div>
            {vgpuGuideSteps.map((item, index) => (
              <button
                key={item.label}
                className={index === activeStep ? "active" : ""}
                onClick={() => setActiveStep(index)}
                aria-label={`查看${item.label}`}
              />
            ))}
          </div>
          <button className="guide-close" onClick={onClose} aria-label="关闭新手引导"><X size={18} /></button>
        </header>
        <div className="guide-copy" key={step.label}>
          <span>STEP {String(activeStep + 1).padStart(2, "0")}</span>
          <h2 id="vgpu-guide-title">{step.label}</h2>
          <strong>{step.title}</strong>
          <p>{step.detail}</p>
          <small>{step.foot}</small>
        </div>
        <footer className="guide-actions">
          <button className="guide-back" disabled={activeStep === 0} onClick={() => setActiveStep((stepIndex) => stepIndex - 1)}>Back</button>
          <button className="guide-next" onClick={() => (lastStep ? onClose() : setActiveStep((stepIndex) => stepIndex + 1))}>
            {lastStep ? "完成阅读" : "Next"}
          </button>
        </footer>
      </section>
    </div>
  );
}

function Curves({ range, setRange }: { range: TimeRange; setRange: (range: TimeRange) => void }) {
  return (
    <div className="curve-panel">
      <div className="curve-top">
        <div><h3>实时监控曲线</h3><p>GPU Util、显存占用、vGPU 使用率、主任务与轻量任务负载对比</p></div>
        <div className="segmented">
          {(["1h", "24h", "7d"] as TimeRange[]).map((item) => (
            <button key={item} className={range === item ? "active" : ""} onClick={() => setRange(item)}>{item === "1h" ? "近 1 小时" : item}</button>
          ))}
        </div>
      </div>
      <ResponsiveContainer height={300}>
        <LineChart data={benefitTrend}>
          <CartesianGrid stroke="#edf0f3" vertical={false} />
          <XAxis dataKey="name" tickLine={false} axisLine={false} />
          <YAxis domain={[0, 100]} tickLine={false} axisLine={false} />
          <Tooltip />
          <Line dataKey="gpu" name="GPU Util" stroke="#111827" strokeWidth={3} dot={false} />
          <Line dataKey="vram" name="显存占用" stroke={accent} strokeWidth={3} dot={false} />
          <Line dataKey="vgpu" name="vGPU 使用率" stroke="#ef4444" strokeWidth={3} dot={{ r: 4 }} />
          <Line dataKey="main" name="主任务" stroke="#334155" strokeDasharray="6 6" />
          <Line dataKey="light" name="轻量任务" stroke="#f59e0b" strokeDasharray="4 6" />
        </LineChart>
      </ResponsiveContainer>
      <div className="risk-note"><AlertTriangle size={17} />峰值重叠时间点：15:00、17:00。建议迁移轻量任务或进入排队。</div>
    </div>
  );
}

function Policy() {
  return (
    <div className="policy-grid">
      <div className="policy-card recommended">
        <span>推荐</span>
        <h3>NVIDIA vGPU 共享模式</h3>
        <p>适合 NvidiaInfer 单卡推理服务，优先复用空闲 GPU 算力。</p>
        <InfoRow label="推荐资源" value="node-gpu-03 / vGPU-03-1" />
        <InfoRow label="资源占比" value="40%" />
        <InfoRow label="预测占用" value="1.2 - 2.6 vGPU" />
        <InfoRow label="失败兜底" value="资源不足时进入高优先级排队" />
      </div>
      <div className="policy-card">
        <span>排队策略</span>
        <h3>高优先级优先处理</h3>
        <p>无法匹配资源时允许排队。高优先级任务按队列权重优先调度，普通任务按进入时间排序。</p>
        <InfoRow label="当前排队" value="3 个实例" />
        <InfoRow label="预计释放" value="约 18 分钟" />
        <InfoRow label="风险动作" value="迁移轻量任务 / 降低共享负载" />
      </div>
    </div>
  );
}

function Instances({
  activeInstance,
  setActiveInstance,
  onCreate,
}: {
  activeInstance: string;
  setActiveInstance: (id: string) => void;
  onCreate: () => void;
}) {
  const [logItem, setLogItem] = useState<(typeof instances)[number] | null>(null);
  const [confirmAction, setConfirmAction] = useState<null | { type: "stop" | "restart" | "release"; item: (typeof instances)[number] }>(null);

  return (
    <>
      <section className="page-stack">
        <div className="summary-grid four-tight">
          <InfoMetric title="实例总数" value="4" desc="包含运行、排队、失败实例" />
          <InfoMetric title="运行中" value="2" desc="当前可对外提供推理服务" />
          <InfoMetric title="排队中" value="1" desc="等待资源或调度完成" />
          <InfoMetric title="失败" value="1" desc="需要人工处理或重新部署" />
        </div>
        <section className="card table-card">
          <div className="table-toolbar">
            <h3>实例列表</h3>
            <div className="segmented"><button className="active">全部 4</button><button>排队中 1</button><button>运行中 2</button><button>失败 1</button></div>
          </div>
          <div className="instance-table">
            <div className="instance-table-head">
              <span>实例</span>
              <span>资源申请</span>
              <span>节点 / 端口</span>
              <span>状态</span>
              <span>到期</span>
              <span>操作</span>
            </div>
            {instances.map((item) => (
              <React.Fragment key={item.id}>
                <div className="instance-row">
                  <div className="instance-name">
                    <button className="expand" onClick={() => setActiveInstance(activeInstance === item.id ? "" : item.id)}>
                      {activeInstance === item.id ? <ChevronDown size={18} /> : <ChevronRight size={18} />}
                    </button>
                    <div><strong>{item.name}</strong><p>{item.id} · {item.model}</p><TagList tags={item.tags} /></div>
                  </div>
                  <div><strong>{item.spec}</strong><p>{item.extra}</p></div>
                  <div><strong>{item.binding.includes("/") ? "自动调度" : item.binding}</strong><p>{item.binding.includes("/") ? `${item.binding.split("/")[0].trim()}：等待分配` : "tcp-8018：30318"}</p></div>
                  <div className="status-stack"><StatusBadge value={item.lifecycle} /><StatusBadge value={item.runtime} /></div>
                  <div><strong>{item.id === "BD-INF-1027" ? "2h 18m" : "6h 00m"}</strong><p>{item.operation}</p></div>
                  <div className="row-actions">
                    <button onClick={() => setLogItem(item)}><FileText size={16} />日志</button>
                    <button onClick={() => setConfirmAction({ type: "stop", item })}>停止</button>
                    <button onClick={() => setConfirmAction({ type: "restart", item })}>重启</button>
                    <button className="danger" onClick={() => setConfirmAction({ type: "release", item })}>释放</button>
                  </div>
                </div>
                {activeInstance === item.id && (
                  <div className="instance-detail">
                    <div className="detail-head"><strong>实例详情 / 只读</strong><span>最后更新：2026-05-13 10:18:32</span></div>
                    <p>用于查看部署配置、运行指标、端口状态与审计线索，不支持在详情内二次编辑。</p>
                    <div className="detail-grid">
                      <InfoTile label="创建人" value={item.creator} />
                      <InfoTile label="创建时间" value="2026-05-13 09:42:18" />
                      <InfoTile label="部署区域" value="Singapore / SG-01" />
                      <InfoTile label="副本数" value="4 个" />
                      <InfoTile label="服务端点" value="https://api.bluedot.ai/v1/qwen-prod" />
                      <InfoTile label="开放端口" value="443 / 8443" />
                      <InfoTile label="资源模式" value={item.resourceMode} />
                      <InfoTile label="绑定资源" value={item.binding} />
                      <InfoTile label="风险等级" value={item.risk} />
                      <InfoTile label="vGPU 预测占用" value="1.2 - 2.6" />
                    </div>
                  </div>
                )}
              </React.Fragment>
            ))}
          </div>
        </section>
      </section>
      {logItem && <LogDrawer item={logItem} onClose={() => setLogItem(null)} />}
      {confirmAction && <InstanceConfirmModal action={confirmAction} onClose={() => setConfirmAction(null)} />}
    </>
  );
}

function InstanceConfirmModal({
  action,
  onClose,
}: {
  action: { type: "stop" | "restart" | "release"; item: (typeof instances)[number] };
  onClose: () => void;
}) {
  const copy = {
    stop: {
      title: "确认停止",
      body: "确认停止该推理实例？停止后服务将不可访问，但配置将保留，可后续重启。",
      ok: "确认",
      danger: false,
    },
    restart: {
      title: "确认重启",
      body: "确认重启该推理实例？重启过程中服务会短暂不可用。",
      ok: "确认",
      danger: false,
    },
    release: {
      title: "确认释放",
      body: "释放后该实例将从运行资源中移除，相关操作记录仍会保留在审计日志中。确认释放？",
      ok: "释放",
      danger: true,
    },
  }[action.type];
  return (
    <div className="action-backdrop">
      <div className="action-modal">
        <h2>{copy.title}</h2>
        <p>{copy.body}</p>
        <div className="action-modal-footer">
          <button className="ghost" onClick={onClose}>Cancel</button>
          <button className={copy.danger ? "danger-solid" : "primary"} onClick={onClose}>{copy.ok}</button>
        </div>
      </div>
    </div>
  );
}

function LogDrawer({ item, onClose }: { item: (typeof instances)[number]; onClose: () => void }) {
  const lines = [
    `[2026-05-13 09:15:00] [INFO] Instance ${item.name} started successfully`,
    "[2026-05-13 09:15:00] [INFO] Health check passed, service is ready",
    `[2026-05-13 09:14:58] [INFO] Model loaded: ${item.model}, VRAM: 42.3GB`,
    `[2026-05-13 09:14:45] [INFO] Loading model weights from /models/${item.name}...`,
    "[2026-05-13 09:14:30] [INFO] Container started, PID: 18432",
    "[2026-05-13 09:14:28] [INFO] Image pulled successfully: qwen:2.5-gpu",
    "[2026-05-13 09:14:00] [INFO] Pulling image qwen:2.5-gpu...",
    `[2026-05-13 09:13:50] [INFO] Allocating vGPU resources in backend pool`,
    "[2026-05-13 09:13:45] [INFO] Scheduling instance to available vGPU lane",
    `[2026-05-13 09:13:40] [INFO] Create request received for ${item.name}`,
  ];
  const text = lines.join("\n");
  return (
    <div className="drawer-backdrop">
      <aside className="log-drawer">
        <header>
          <h2>实例日志 — {item.id}</h2>
          <button className="close-inline" onClick={onClose}><X size={30} /></button>
        </header>
        <div className="log-tools">
          <label><Search size={22} /><input placeholder="搜索日志" /></label>
          <button className="ghost" onClick={() => navigator.clipboard?.writeText(text)}>复制</button>
          <label className="check-label"><input type="checkbox" defaultChecked /> 自动滚动</label>
        </div>
        <pre>{text}</pre>
      </aside>
    </div>
  );
}

function Pending({ onCreate }: { onCreate: () => void }) {
  return <Drafts onCreate={onCreate} />;
}

function Ports() {
  const [allowlist, setAllowlist] = useState(ports);
  const [portValue, setPortValue] = useState("");
  const [usageValue, setUsageValue] = useState("");
  const [portError, setPortError] = useState("");
  const portHint = "端口需为 1-65535 的整数，且不能重复。";

  const addPort = () => {
    const normalized = portValue.trim();
    const portNumber = Number(normalized);
    const invalid =
      !/^\d+$/.test(normalized) ||
      !Number.isInteger(portNumber) ||
      portNumber < 1 ||
      portNumber > 65535 ||
      allowlist.some((item) => item.port === normalized);

    if (invalid) {
      setPortError(portHint);
      return;
    }

    setAllowlist((current) => [
      ...current,
      {
        id: Math.random().toString(16).slice(2, 10),
        port: normalized,
        usage: usageValue.trim() || "未填写",
        creator: "admin",
        date: "2026-05-13 18:30:00",
      },
    ]);
    setPortValue("");
    setUsageValue("");
    setPortError("");
  };

  return (
    <section className="page-stack">
      <section className="ports-layout">
        <section className="card form-card">
        <div className="card-head">
          <div>
            <h2>新增端口白名单</h2>
            <p>端口会参与资源预检，避免 NodePort 冲突。</p>
          </div>
        </div>
        <label>
          端口号
          <input
            className={portError ? "field-error" : ""}
            inputMode="numeric"
            placeholder="例如：50056"
            value={portValue}
            onChange={(event) => {
              setPortValue(event.target.value);
              if (portError) setPortError("");
            }}
          />
          {portError && <span className="form-error">{portError}</span>}
        </label>
        <label>
          放行原因 / 备注
          <textarea
            placeholder="例如：web api 调试占用"
            value={usageValue}
            onChange={(event) => setUsageValue(event.target.value)}
          />
        </label>
        <button className="dark-button" onClick={addPort}>新增</button>
        </section>
        <section className="card">
        <div className="card-head"><div><h2>端口白名单列表</h2><p>Allowlist: [{allowlist.map((item) => item.port).join(", ")}]</p></div></div>
        {allowlist.map((port) => (
          <div className="port-row" key={port.id}>
            <div><small>{port.id}</small><p>创建人：{port.creator}</p></div>
            <strong>{port.port}</strong>
            <div><b>{port.usage}</b><p>{port.date}</p></div>
            <button className="danger-outline">Remove</button>
          </div>
        ))}
        </section>
      </section>
    </section>
  );
}

function Alerts({ filter, setFilter }: { filter: string; setFilter: (filter: string) => void }) {
  const filtered = filter === "全部层级" ? alerts : alerts.filter((alert) => alert.level === filter);
  const [toast, setToast] = useState("");
  const markResolved = () => {
    setToast("已标记解决，可在历史记录查看");
    window.setTimeout(() => setToast(""), 2600);
  };
  return (
    <section className="page-stack">
      <div className="summary-grid four-tight">
        <InfoMetric title="未处理告警" value="4" desc="High 2 / Medium 1 / Low 1" />
        <InfoMetric title="高" value="2" desc="未解决" />
        <InfoMetric title="平均处理时长" value="7m" desc="-18%" />
        <InfoMetric title="健康评分" value="86" desc="Stable" />
      </div>
      <section className="card categories">
        <div className="card-head"><div><h2>异常类别</h2><p>GPU/NPU 推理平台常见异常状态类别</p></div><AlertTriangle color="#ef4444" /></div>
        {["实例 Pending 超时", "实例启动失败", "实例运行异常", "实例已过期", "节点显存偏高", "vGPU 资源超限", "峰值重叠风险", "端口冲突", "配额不足", "镜像拉取失败"].map((name, index) => (
          <div className="category" key={name}><small>{String(index + 1).padStart(2, "0")}</small><strong>{name}</strong></div>
        ))}
      </section>
      <div className="filter-card">
        <strong>告警层级</strong>
        <div className="segmented">
          {["全部层级", "高", "中", "低"].map((item) => <button className={filter === item ? "active" : ""} onClick={() => setFilter(item)} key={item}>{item}</button>)}
        </div>
      </div>
      <section className="card">
        <div className="card-head"><div><h2>实时告警</h2><p>优先处理影响部署与资源回收的问题</p></div><AlertTriangle color="#ef4444" /></div>
        <div className="alert-list-full">
          {filtered.map((alert) => <AlertItem alert={alert} key={`${alert.level}-${alert.title}`} onResolve={markResolved} />)}
        </div>
      </section>
      <section className="card resolved">
        <div className="card-head"><div><h2>已解决历史记录</h2><p>已解决告警沉淀为历史记录，用于追溯处理人、处理时间与异常类型。</p></div></div>
        <table>
          <thead><tr><th>告警层级</th><th>异常类别</th><th>Target</th><th>Owner</th><th>Resolved By</th><th>Resolved At</th></tr></thead>
          <tbody><tr><td>高</td><td>实例 Pending 超时</td><td>nvidia-cuda-b7d93e</td><td>ops</td><td>admin</td><td>2026-05-13 14:05:19</td></tr></tbody>
        </table>
      </section>
      {toast && <div className="toast">{toast}</div>}
    </section>
  );
}

function Audit() {
  const [resultFilter, setResultFilter] = useState("全部结果");
  const [operatorFilter, setOperatorFilter] = useState("全部操作人");
  const [timeFilter, setTimeFilter] = useState("近 7 天");
  const [auditSearch, setAuditSearch] = useState("");
  const [exporting, setExporting] = useState<"" | "excel" | "pdf">("");
  const [importOpen, setImportOpen] = useState(false);
  const [importing, setImporting] = useState(false);
  const [importReady, setImportReady] = useState(false);
  const [exportMenuOpen, setExportMenuOpen] = useState(false);
  const operators = Array.from(new Set(audits.map((audit) => audit[0])));
  const filteredAudits = audits.filter((audit) => {
    const resultMatched = resultFilter === "全部结果" || audit[3] === resultFilter;
    const operatorMatched = operatorFilter === "全部操作人" || audit[0] === operatorFilter;
    const keyword = auditSearch.trim().toLowerCase();
    const searchMatched = !keyword || audit.join(" ").toLowerCase().includes(keyword);
    return resultMatched && operatorMatched && searchMatched;
  });
  const exportAudit = (type: "excel" | "pdf") => {
    setExporting(type);
    setExportMenuOpen(false);
    window.setTimeout(() => setExporting(""), 1400);
  };
  const startImport = () => {
    setImportReady(false);
    setImporting(true);
    window.setTimeout(() => {
      setImporting(false);
      setImportReady(true);
    }, 1600);
  };

  return (
    <>
      <section className="card audit-card">
        <div className="card-head audit-card-head">
          <div><h2>审计日志</h2><p>记录虚拟卡推荐、策略创建、告警处理与实例运维操作。</p></div>
          <div className="audit-actions">
            <label className="audit-search"><Search size={17} /><input value={auditSearch} onChange={(event) => setAuditSearch(event.target.value)} placeholder="搜索操作、对象、结果" /></label>
            <button className="ghost compact" onClick={() => { setImportReady(false); setImportOpen(true); }} disabled={!!exporting}>
              <Download size={16} />导入日志
            </button>
            <div className="export-menu-wrap">
              <button className="ghost compact" onClick={() => setExportMenuOpen((open) => !open)} disabled={!!exporting}>
                {exporting ? <i className="export-spinner" /> : <FileText size={16} />}导出日志<ChevronDown size={15} />
              </button>
              {exportMenuOpen && (
                <div className="export-menu">
                  <button onClick={() => exportAudit("excel")}><Download size={15} />导出 Excel</button>
                  <button onClick={() => exportAudit("pdf")}><FileText size={15} />导出 PDF</button>
                </div>
              )}
            </div>
          </div>
        </div>
        <div className="audit-filters">
          <label><span>结果</span><select value={resultFilter} onChange={(event) => setResultFilter(event.target.value)}><option>全部结果</option><option>成功</option><option>通过</option><option>失败</option></select></label>
          <label><span>操作人</span><select value={operatorFilter} onChange={(event) => setOperatorFilter(event.target.value)}><option>全部操作人</option>{operators.map((operator) => <option key={operator}>{operator}</option>)}</select></label>
          <label><span>时间范围</span><select value={timeFilter} onChange={(event) => setTimeFilter(event.target.value)}><option>近 7 天</option><option>近 24 小时</option><option>近 30 天</option><option>自定义</option></select></label>
        </div>
        {exporting && <div className="export-reading"><i /><span>正在读取并分解审计日志，生成 {exporting === "excel" ? "Excel" : "PDF"} 文件...</span></div>}
        <table>
          <thead><tr><th>操作人</th><th>操作类型</th><th>操作对象</th><th>操作结果</th><th>操作时间</th></tr></thead>
          <tbody>
            {filteredAudits.map((audit) => (
              <tr key={audit.join("-")}><td><strong>{audit[0]}</strong></td><td>{audit[1]}</td><td><code>{audit[2]}</code></td><td><StatusBadge value={audit[3]} /></td><td>{audit[4]}</td></tr>
            ))}
          </tbody>
        </table>
      </section>
      {importOpen && <ImportLogModal importing={importing} importReady={importReady} onImport={startImport} onClose={() => setImportOpen(false)} />}
    </>
  );
}

function ImportLogModal({ importing, importReady, onImport, onClose }: { importing: boolean; importReady: boolean; onImport: () => void; onClose: () => void }) {
  return (
    <div className="modal-backdrop">
      <section className="import-modal">
        <header>
          <div><h2>导入日志</h2><p>可上传Excel、PDF格式文件</p></div>
          <button className="close" onClick={onClose}><X /></button>
        </header>
        <label className={cx("upload-dropzone", importing && "is-uploading")}>
          <input type="file" accept=".xlsx,.xls,.pdf" onChange={onImport} disabled={importing} />
          <FileText size={28} />
          <strong>{importing ? "正在上传并解析日志" : importReady ? "日志解析完成" : "拖拽文件到这里，或点击选择本地文件"}</strong>
          <span>{importing ? "读取文件结构、拆分表格与页面内容..." : importReady ? "进度 100%，可点击确定导入" : "支持 .xlsx / .xls / .pdf"}</span>
          {(importing || importReady) && <i className={cx("upload-progress", importReady && "done")} />}
        </label>
        <footer>
          <button className="ghost" onClick={onClose}>取消</button>
          <button className="primary" onClick={onClose} disabled={!importReady || importing}>确定</button>
        </footer>
      </section>
    </div>
  );
}

function Drafts({ onCreate }: { onCreate: () => void }) {
  return (
    <section className="page-stack">
      <div className="draft-grid">
        {drafts.map((draft) => (
          <article className="card draft-card" key={draft.name}>
            <div className="card-head">
              <div>
                <h3>{draft.name}</h3>
                <p>{draft.meta}</p>
              </div>
              <StatusBadge value="草稿" />
            </div>
            <div className="metric-split"><InfoTile label="资源类型" value={draft.resource} /><InfoTile label="GPU 数量" value={`${draft.gpu}`} /></div>
            <div className="actions-row"><button className="ghost compact">继续编辑</button><button className="primary compact" onClick={onCreate}>从草稿创建</button><button className="danger-outline">删除草稿</button></div>
          </article>
        ))}
      </div>
    </section>
  );
}

function CreateModal({ onClose }: { onClose: () => void }) {
  const [checked, setChecked] = useState(false);
  const [checking, setChecking] = useState(false);
  const [step, setStep] = useState<1 | 2 | 3>(1);
  const [deployType, setDeployType] = useState("NvidiaInfer");
  const [resourceName, setResourceName] = useState("NVIDIA/GPU");
  const [deviceCount, setDeviceCount] = useState("1");
  const isHuawei = resourceName === "Huawei/Ascend310P";
  const resourceInsufficient = checked && Number(deviceCount) > 1;
  const k8sResourceName = isHuawei ? "huawei.com/Ascend310P" : "nvidia.com/gpu";
  const vgpuMin = (Number(deviceCount) * 1.2).toFixed(1);
  const vgpuMax = (Number(deviceCount) * 2.6).toFixed(1);
  const checks = checked
    ? [["资源设备可用", resourceInsufficient ? "不足" : "通过"], ["CPU / 内存余量", "通过"], ["NodePort 自动避让", "通过"], ["部署锁与并发校验", "通过"], ["创建人审计标记", "通过"], ["vGPU 预测占用", `${vgpuMin} - ${vgpuMax}`]]
    : [["资源设备可用", "待检测"], ["CPU / 内存余量", "待检测"], ["NodePort 自动避让", "待检测"], ["部署锁与并发校验", "待检测"], ["创建人审计标记", "待检测"], ["vGPU 预测占用", "待检测"]];
  const startPrecheck = () => {
    setChecked(false);
    setChecking(true);
    window.setTimeout(() => {
      setChecking(false);
      setChecked(true);
      setStep(3);
    }, 1200);
  };
  const resetPrecheck = () => {
    setChecked(false);
    setChecking(false);
    setStep(1);
  };
  return (
    <div className="modal-backdrop">
      <div className="create-modal">
        <header>
          <div><h2>创建实例</h2><p>完成基础信息、资源配置、服务配置与资源预检填写。资源不足或配置未完成时保存到实例中心的待发布。</p></div>
          <button className="close" onClick={onClose}><X /></button>
        </header>
        <div className="create-steps">
          {["填写配置", "资源预检", "创建/排队/保存草稿"].map((label, index) => (
            <button key={label} className={cx(step === index + 1 && "active", step > index + 1 && "done")} onClick={() => setStep((index + 1) as 1 | 2 | 3)} disabled={index === 2 && !checked}>
              <span>{index + 1}</span>{label}
            </button>
          ))}
        </div>
        <div className="modal-body">
          {step === 1 && (
            <section className="card modal-form">
              <h3>基础信息</h3>
              <label>展示名称<input defaultValue="nvidia-cuda-auto-001" /><small>用于前端识别，当前后端会自动生成 deployment_name。</small></label>
              <div className="form-grid">
              <label>部署类型<select value={deployType} onChange={(event) => { setDeployType(event.target.value); resetPrecheck(); }}><option>NvidiaInfer</option><option>HuaweiInfer</option></select></label>
              <label>资源设备<select value={resourceName} onChange={(event) => {
                const next = event.target.value;
                setResourceName(next);
                setDeployType(next === "Huawei/Ascend310P" ? "HuaweiInfer" : "NvidiaInfer");
                if (next === "Huawei/Ascend310P") setDeviceCount("1");
                resetPrecheck();
              }}><option>NVIDIA/GPU</option><option>Huawei/Ascend310P</option></select></label>
              <label>设备数量<select value={deviceCount} onChange={(event) => { setDeviceCount(event.target.value); resetPrecheck(); }}><option>1</option><option disabled={isHuawei}>2</option><option disabled={isHuawei}>4</option></select></label>
              <label>创建人<input defaultValue="admin" disabled /></label>
              <label>请求 ID<input defaultValue="c-001" /></label>
              <label>请求序列<input defaultValue="s-001" /></label>
              </div>
              <label>请求上下文<input defaultValue="create inference instance" /></label>
              <div className="form-grid resource-config-grid">
                <label>K8s 资源名<input value={k8sResourceName} disabled readOnly /><small>提交 Huawei 时作为 gpu_resource_name；NVIDIA 由后端映射为 nvidia.com/gpu。</small></label>
                <label>NodePort 策略<input value="后端自动分配，避让 30000-59999 已占用端口" disabled readOnly /></label>
              </div>
              <div className="api-preview">
                <strong>提交结构</strong>
                <code>{`content.devices["${resourceName}"] = ${deviceCount}`}</code>
                <code>{`content.deployType = "${deployType}"`}</code>
                <code>{`content.creator = "admin"`}</code>
              </div>
            </section>
          )}
          {step === 1 && <div className="modal-side single-side">
            <section className="card recommendation">
              <span>推荐</span>
              <h3>推荐：后台 vGPU 自动调度</h3>
              <p>前台不选择具体物理 GPU，由后端基于资源余量、端口冲突和并发锁完成创建。</p>
              <InfoRow label="推荐资源" value={isHuawei ? "Ascend310P 后台调度池" : "NVIDIA vGPU 共享资源池"} />
              <InfoRow label="预计占用" value={`${vgpuMin} - ${vgpuMax} vGPU`} />
              <InfoRow label="资源切分" value="单 GPU 默认拆分 2 个 vGPU" />
              <InfoRow label="风险等级" value={resourceInsufficient ? "中，建议排队" : "低"} />
              <InfoRow label="推荐理由" value="字段更贴近后端真实入参，减少无效配置" />
              <InfoRow label="失败兜底" value="资源不足时进入排队或保存待发布" />
            </section>
          </div>}
          {step === 2 && (
            <section className="card precheck">
              <div className="precheck-head"><div><h3>资源预检</h3><p>校验资源设备、CPU、内存与端口可用性；镜像和容器端口由后端默认模板控制。</p></div><button className="primary" onClick={startPrecheck} disabled={checking}>{checking ? "检测中" : "开始预检"}</button></div>
              {checks.map(([label, value]) => checking ? <PrecheckLoadingRow key={label} label={label} /> : <InfoRow key={label} label={label} value={value} />)}
            </section>
          )}
          {step === 3 && (
            <section className="card precheck create-result">
              <div className="precheck-head">
                <div><h3>{resourceInsufficient ? "资源不足，建议排队" : "资源预检通过"}</h3><p>{resourceInsufficient ? "当前资源已满,可先保存至草稿箱或者进行排队(当资源空出后执行)" : "当前配置可提交创建，后端将自动完成 vGPU 调度与端口避让。"}</p></div>
                <StatusBadge value={resourceInsufficient ? "资源已满" : "通过"} />
              </div>
              <div className="result-grid precheck-result-list">
                {checks.map(([label, value]) => <InfoRow key={label} label={label} value={value} />)}
              </div>
            </section>
          )}
        </div>
        <footer>
          <button className="ghost">保存草稿</button>
          <div>
            {step > 1 && <button className="ghost" onClick={() => setStep((step - 1) as 1 | 2)}>上一步</button>}
            <button className="ghost" onClick={onClose}>取消</button>
            {step === 1 && <button className="primary" onClick={() => setStep(2)}>下一步</button>}
            {step === 2 && <button className="primary" onClick={startPrecheck} disabled={checking}>{checking ? "检测中" : "开始预检"}</button>}
            {step === 3 && <button className={cx("primary", resourceInsufficient && "queue")}>{resourceInsufficient ? "排队" : "确认创建"}</button>}
          </div>
        </footer>
      </div>
    </div>
  );
}

function PrecheckLoadingRow({ label }: { label: string }) {
  return (
    <div className="info-row precheck-loading-row">
      <span>{label}</span>
      <strong><i className="precheck-spinner" aria-hidden="true" />检测中</strong>
    </div>
  );
}

function AlertsCompact({ setPage }: { setPage: (page: Page) => void }) {
  return (
    <section className="card alerts-card">
      <div className="card-head">
        <div><h2>实时告警</h2><p>优先处理影响部署与资源回收的问题</p></div>
        <button className="ghost compact" onClick={() => setPage("alerts")}>查看全部</button>
      </div>
      <div className="alert-list-full compact-list">
        {alerts.slice(0, 5).map((alert) => <AlertItem alert={alert} key={alert.title} compact />)}
      </div>
    </section>
  );
}

function AlertItem({ alert, compact = false, onResolve }: { alert: (typeof alerts)[number]; compact?: boolean; onResolve?: () => void }) {
  return (
    <div className={cx("alert-item", compact && "compact")}>
      <div>
        <span className={cx("level-badge", alert.level === "高" && "high", alert.level === "中" && "mid")}>{alert.level}</span>
        <span className="category-pill">{alert.category}</span>
        <strong>{alert.title}</strong>
        <p>{alert.desc}</p>
        <code>{alert.target}</code>
        {!compact && <em>推荐处理动作：{alert.action}</em>}
      </div>
      <aside><span>{alert.time}</span>{!compact && <button onClick={onResolve}>标记解决</button>}</aside>
    </div>
  );
}

function AnimatedNumber({ value, suffix = "", run, delay = 0 }: { value: number; suffix?: string; run: number; delay?: number }) {
  const [displayValue, setDisplayValue] = useState(value);
  const lastRun = useRef(run);

  useEffect(() => {
    const prefersReducedMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    if (!run || run === lastRun.current || prefersReducedMotion) {
      setDisplayValue(value);
      lastRun.current = run;
      return;
    }

    let frame = 0;
    let startTime = 0;
    const duration = 1400;
    const timeout = window.setTimeout(() => {
      const tick = (timestamp: number) => {
        if (!startTime) startTime = timestamp;
        const progress = Math.min((timestamp - startTime) / duration, 1);
        const eased = 1 - Math.pow(1 - progress, 3);
        setDisplayValue(Math.round(value * eased));
        if (progress < 1) {
          frame = window.requestAnimationFrame(tick);
        } else {
          setDisplayValue(value);
        }
      };
      frame = window.requestAnimationFrame(tick);
    }, delay);

    lastRun.current = run;
    return () => {
      window.clearTimeout(timeout);
      window.cancelAnimationFrame(frame);
    };
  }, [delay, run, value]);

  return <span className="animated-number"><span>{displayValue}</span>{suffix}</span>;
}

function InfoMetric({ title, value, desc }: { title: string; value: string; desc: string }) {
  return <div className="metric-card small"><span>{title}</span><strong>{value}</strong><p>{desc}</p></div>;
}

function InfoTile({ label, value }: { label: string; value: string }) {
  return <div className="info-tile"><span>{label}</span><strong>{value}</strong></div>;
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return <div className="info-row"><span>{label}</span><strong>{value}</strong></div>;
}

function TagList({ tags }: { tags: string[] }) {
  return <div className="tags">{tags.map((tag) => <span key={tag}>{tag}</span>)}</div>;
}

function TopoCard({ label, title, lines, bar, warning }: { label: string; title: string; lines: string[]; bar?: boolean; warning?: boolean }) {
  return (
    <div className={cx("topo-card", warning && "warn")}>
      <span>{label}</span>
      <strong>{title}</strong>
      {bar && <div className="split-bar"><i>40%</i><i>40%</i><i>预留</i></div>}
      {lines.map((line) => <p key={line}>{line}</p>)}
    </div>
  );
}

function LogoUploadModal({ onClose, onUploaded }: { onClose: () => void; onUploaded: (url: string) => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState("");
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");

  const handleFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const selected = event.target.files?.[0];
    if (!selected) return;
    setFile(selected);
    setError("");

    const reader = new FileReader();
    reader.onload = () => setPreview(reader.result as string);
    reader.readAsDataURL(selected);
  };

  const handleUpload = async () => {
    if (!file) {
      setError("请先选择文件");
      return;
    }
    setUploading(true);
    setError("");
    try {
      const result = await uploadSystemLogo(file);
      onUploaded(result.logo_url);
    } catch (err: any) {
      setError(err.message || "上传失败");
    } finally {
      setUploading(false);
    }
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <section className="logo-upload-modal" onClick={(e) => e.stopPropagation()}>
        <header>
          <div>
            <h2>更换 Logo</h2>
            <p>上传新图片替换侧边栏和登录页的 Logo，支持 PNG / JPG / SVG / GIF，≤ 2 MB</p>
          </div>
          <button className="close" onClick={onClose}><X /></button>
        </header>

        <label className={cx("upload-dropzone", !!file && "has-file")}>
          <input type="file" accept=".png,.jpg,.jpeg,.svg,.gif" onChange={handleFileChange} disabled={uploading} />
          {preview ? (
            <img className="logo-preview" src={preview} alt="预览" />
          ) : (
            <>
              <Image size={32} />
              <strong>拖拽或点击选择图片</strong>
              <span>PNG · JPG · SVG · GIF（≤ 2 MB）</span>
            </>
          )}
        </label>

        {error && <p className="form-error" style={{ marginTop: 12 }}>{error}</p>}

        <footer>
          <button className="ghost" onClick={onClose} disabled={uploading}>取消</button>
          <button className="primary" onClick={handleUpload} disabled={uploading || !file}>
            {uploading ? "上传中..." : "确认更换"}
          </button>
        </footer>
      </section>
    </div>
  );
}

const styles = `
`;

createRoot(document.getElementById("root")!).render(<App />);
