export type DeployResourceName = "NVIDIA/GPU" | "Huawei/Ascend310P";
export type DeployType = "NvidiaInfer" | "HuaweiInfer";

export type ApiEnvelope<T> = {
  msg_id: string;
  serial: string;
  context: string;
  content: T;
  gpu_resource_name?: string;
};

export type ApiResponse<T> = {
  msg_id: string;
  head_id: number;
  context: string;
  serial: string;
  version: string;
  status: number;
  content: T;
  token: string;
  time: string;
  timestamp: number;
  http_status_code: number;
  msg: string;
  is_success: boolean;
};

export type CreateDeployContent = {
  devices: Record<DeployResourceName | string, number>;
  deployType: DeployType;
  creator: string;
  instance_name?: string;
};

export type CreateDeployResult = {
  deployment_name: string;
  node_ports: Array<{ name: string; port: number }>;
  devices: Record<string, number>;
  gpu_type?: string;
  deployType: DeployType;
  log_path: string;
};

export type DeployPrecheckResult = {
  can_create: boolean;
  reason: string;
  cpu_available_m?: number;
  mem_available_bytes?: number;
  gpu_details?: Record<string, {
    requested: number;
    available: number;
    total: number;
    used: number;
  }>;
  total_deployments?: number;
  devices: Record<string, number>;
};

export type DeployNamePayload = {
  name: string;
};

export type QueueDeployPayload = DeployNamePayload & {
  priority: "high" | "normal" | "low";
  reason?: string;
};

export type PortAllowlistItem = {
  id?: string;
  port: number;
  name: string;
  creator: string;
  created_at?: string;
  remark?: string;
};

export type AlertItem = {
  id: string;
  level: "high" | "medium" | "low";
  category: string;
  title: string;
  target: string;
  description: string;
  action: string;
  created_at: string;
  status: "open" | "resolved";
};

export type AuditQuery = {
  result?: "all" | "success" | "passed" | "failed";
  operator?: string;
  time_range?: "24h" | "7d" | "30d" | "custom";
  keyword?: string;
  page?: number;
  page_size?: number;
};

export type AuditRecord = {
  operator: string;
  action: string;
  target: string;
  result: string;
  created_at: string;
};

export type PagedResult<T> = {
  list: T[];
  total: number;
  page: number;
  page_size: number;
};

export type LogLine = {
  time: string;
  level: "INFO" | "WARN" | "ERROR";
  message: string;
};

const API_BASE = import.meta.env.VITE_API_BASE_URL || "";

const DEPLOY_ACTION_META = {
  check: { prefix: "check", context: "check deploy available" },
  create: { prefix: "create", context: "create inference instance" },
  retrieve: { prefix: "retrieve", context: "retrieve deploy" },
  list: { prefix: "list", context: "list deploy" },
  release: { prefix: "release", context: "release deploy" },
  reset: { prefix: "reset", context: "restart deploy" },
  stop: { prefix: "stop", context: "stop deploy" },
  logs: { prefix: "logs", context: "deploy logs" },
} as const;

type DeployAction = keyof typeof DEPLOY_ACTION_META;

function withDeployActionEnvelope<T>(payload: ApiEnvelope<T>, action: DeployAction): ApiEnvelope<T> {
  const meta = DEPLOY_ACTION_META[action];
  const now = Date.now();
  return {
    ...payload,
    msg_id: payload.msg_id?.startsWith(`${meta.prefix}-`) ? payload.msg_id : `${meta.prefix}-${now}`,
    serial: payload.serial?.startsWith(`${meta.prefix}-`) ? payload.serial : `${meta.prefix}-serial-${now}`,
    context: meta.context,
  };
}

function resourceToDeployType(resourceName: DeployResourceName): DeployType {
  return resourceName === "Huawei/Ascend310P" ? "HuaweiInfer" : "NvidiaInfer";
}

function resourceToK8sName(resourceName: DeployResourceName) {
  return resourceName === "Huawei/Ascend310P" ? "huawei.com/Ascend310P" : undefined;
}

export function buildCreateDeployPayload(params: {
  resourceName: DeployResourceName;
  deviceCount: number;
  creator: string;
  msgId?: string;
  serial?: string;
  context?: string;
}): ApiEnvelope<CreateDeployContent> {
  const deployType = resourceToDeployType(params.resourceName);
  const envelope: ApiEnvelope<CreateDeployContent> = {
    msg_id: params.msgId || `create-${Date.now()}`,
    serial: params.serial || `serial-${Date.now()}`,
    context: params.context || "create inference instance",
    content: {
      devices: { [params.resourceName]: params.deviceCount },
      deployType,
      creator: params.creator,
    },
  };

  const gpuResourceName = resourceToK8sName(params.resourceName);
  if (gpuResourceName) envelope.gpu_resource_name = gpuResourceName;
  return envelope;
}

async function requestApi<TResponse, TBody>(path: string, body: TBody, user = "admin"): Promise<ApiResponse<TResponse>> {
  const response = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-User": user,
    },
    body: JSON.stringify(body),
  });
  const data = await response.json() as ApiResponse<TResponse>;
  if (!response.ok || !data.is_success) {
    throw new Error(data.msg || `API request failed: ${response.status}`);
  }
  return data;
}

export function checkDeployAvailable(payload: ApiEnvelope<CreateDeployContent>) {
  return requestApi<DeployPrecheckResult, ApiEnvelope<CreateDeployContent>>("/api/deploy/check-available", withDeployActionEnvelope(payload, "check"), payload.content.creator);
}

export function createDeploy(payload: ApiEnvelope<CreateDeployContent>) {
  return requestApi<CreateDeployResult, ApiEnvelope<CreateDeployContent>>("/api/deploy/create-default", withDeployActionEnvelope(payload, "create"), payload.content.creator);
}

export function retrieveDeploy(payload: ApiEnvelope<DeployNamePayload>) {
  return requestApi<unknown, ApiEnvelope<DeployNamePayload>>("/api/deploy/retrieve", withDeployActionEnvelope(payload, "retrieve"));
}

export function releaseDeploy(payload: ApiEnvelope<DeployNamePayload>) {
  return requestApi<unknown, ApiEnvelope<DeployNamePayload>>("/api/deploy/release", withDeployActionEnvelope(payload, "release"));
}

export function resetDeploy(payload: ApiEnvelope<DeployNamePayload>) {
  return requestApi<unknown, ApiEnvelope<DeployNamePayload>>("/api/deploy/reset", withDeployActionEnvelope(payload, "reset"));
}

export function stopDeploy(payload: ApiEnvelope<DeployNamePayload>) {
  return requestApi<unknown, ApiEnvelope<DeployNamePayload>>("/api/deploy/stop", withDeployActionEnvelope(payload, "stop"));
}

export function queueDeploy(payload: ApiEnvelope<QueueDeployPayload>) {
  return requestApi<unknown, ApiEnvelope<QueueDeployPayload>>("/api/deploy/queue", payload, payload.content.name);
}

export function listDeployments(payload: Omit<ApiEnvelope<Record<string, never>>, "content"> & { content?: Record<string, never> }) {
  return requestApi<unknown, ApiEnvelope<Record<string, never>>>("/api/deploy/list", withDeployActionEnvelope({ ...payload, content: payload.content || {} }, "list"));
}

export function getDeployLogs(payload: ApiEnvelope<DeployNamePayload>) {
  return requestApi<LogLine[], ApiEnvelope<DeployNamePayload>>("/api/deploy/logs", withDeployActionEnvelope(payload, "logs"));
}

export function listPortAllowlist(payload: ApiEnvelope<Record<string, never>>) {
  return requestApi<PortAllowlistItem[], ApiEnvelope<Record<string, never>>>("/api/ports/allowlist/list", payload);
}

export function createPortAllowlist(payload: ApiEnvelope<Pick<PortAllowlistItem, "port" | "name" | "creator" | "remark">>) {
  return requestApi<PortAllowlistItem, ApiEnvelope<Pick<PortAllowlistItem, "port" | "name" | "creator" | "remark">>>("/api/ports/allowlist/create", payload, payload.content.creator);
}

export function deletePortAllowlist(payload: ApiEnvelope<{ id?: string; port: number }>) {
  return requestApi<unknown, ApiEnvelope<{ id?: string; port: number }>>("/api/ports/allowlist/delete", payload);
}

export function listAlerts(payload: ApiEnvelope<{ level?: "all" | "high" | "medium" | "low"; limit?: number }>) {
  return requestApi<AlertItem[], ApiEnvelope<{ level?: "all" | "high" | "medium" | "low"; limit?: number }>>("/api/alerts/list", payload);
}

export function resolveAlert(payload: ApiEnvelope<{ id: string; resolver: string }>) {
  return requestApi<unknown, ApiEnvelope<{ id: string; resolver: string }>>("/api/alerts/resolve", payload, payload.content.resolver);
}

export function listAudits(payload: ApiEnvelope<AuditQuery>) {
  return requestApi<PagedResult<AuditRecord>, ApiEnvelope<AuditQuery>>("/api/audits/list", payload);
}

export function importAuditLogs(formData: FormData, user = "admin") {
  return fetch(`${API_BASE}/api/audits/import`, {
    method: "POST",
    headers: { "X-User": user },
    body: formData,
  });
}

export function exportAuditLogs(payload: ApiEnvelope<AuditQuery & { format: "excel" | "pdf" }>) {
  return requestApi<{ download_url: string }, ApiEnvelope<AuditQuery & { format: "excel" | "pdf" }>>("/api/audits/export", payload);
}

// --- 系统 Logo ---

export type LogoResponse = {
  logo_url: string;
  logo_enabled: boolean;
};

export async function fetchSystemLogo(): Promise<LogoResponse> {
  const response = await fetch(`${API_BASE}/api/system/logo`);
  if (!response.ok) {
    return { logo_url: "", logo_enabled: false };
  }
  const data = await response.json();
  return {
    logo_url: data?.logo_url || "",
    logo_enabled: data?.logo_enabled === true,
  };
}

export async function uploadSystemLogo(file: File, user = "admin"): Promise<LogoResponse> {
  const formData = new FormData();
  formData.append("logo", file);

  const response = await fetch(`${API_BASE}/api/system/logo`, {
    method: "POST",
    headers: { "X-User": user },
    body: formData,
  });

  const data = await response.json();
  if (!response.ok || !data.is_success) {
    throw new Error(data.msg || "Logo 上传失败");
  }
  return {
    logo_url: data.logo_url || "",
    logo_enabled: data.logo_enabled === true,
  };
}

export async function enableLogo(user = "admin"): Promise<LogoResponse> {
  const response = await fetch(`${API_BASE}/api/system/logo/enable`, {
    method: "PUT",
    headers: { "Content-Type": "application/json", "X-User": user },
  });
  const data = await response.json();
  if (!response.ok || !data.is_success) {
    throw new Error(data.msg || "启用 Logo 失败");
  }
  return {
    logo_url: data.logo_url || "",
    logo_enabled: data.logo_enabled === true,
  };
}

export async function disableLogo(user = "admin"): Promise<LogoResponse> {
  const response = await fetch(`${API_BASE}/api/system/logo/disable`, {
    method: "PUT",
    headers: { "Content-Type": "application/json", "X-User": user },
  });
  const data = await response.json();
  if (!response.ok || !data.is_success) {
    throw new Error(data.msg || "恢复默认失败");
  }
  return {
    logo_url: data.logo_url || "",
    logo_enabled: data.logo_enabled === true,
  };
}
