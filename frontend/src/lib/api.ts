/**
 * API client — axios wrapper with auth token injection.
 */
import axios from "axios";

const apiClient = axios.create({
  baseURL: process.env.NEXT_PUBLIC_API_URL + "/api/v1",
  headers: { "Content-Type": "application/json" },
});

apiClient.interceptors.request.use((config) => {
  if (typeof window !== "undefined") {
    const token = localStorage.getItem("access_token");
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
  }
  return config;
});

apiClient.interceptors.response.use(
  (res) => res,
  async (error) => {
    if (error.response?.status === 401) {
      const refreshToken = localStorage.getItem("refresh_token");
      if (refreshToken) {
        try {
          const res = await axios.post(
            process.env.NEXT_PUBLIC_API_URL + "/api/v1/auth/refresh",
            { refresh_token: refreshToken }
          );
          localStorage.setItem("access_token", res.data.access_token);
          localStorage.setItem("refresh_token", res.data.refresh_token);
          error.config.headers.Authorization = `Bearer ${res.data.access_token}`;
          return apiClient.request(error.config);
        } catch {
          localStorage.removeItem("access_token");
          localStorage.removeItem("refresh_token");
          window.location.href = "/login";
        }
      }
    }
    return Promise.reject(error);
  }
);

export { apiClient };
export default apiClient;

// ── API helpers ───────────────────────────────────────────────────────────────
export const authApi = {
  login: (username: string, password: string) =>
    apiClient.post("/auth/login", { username, password }),
  register: (data: { email: string; username: string; password: string; full_name?: string }) =>
    apiClient.post("/auth/register", data),
  refresh: (refreshToken: string) =>
    apiClient.post("/auth/refresh", { refresh_token: refreshToken }),
  getSSOAuthUrl: (provider: string) =>
    apiClient.get(`/auth/sso/${provider}/authorize`),
  ssoCallback: (provider: string, code: string, state: string) =>
    apiClient.post("/auth/sso/callback", { provider, code, state }),
};

export const userApi = {
  me: () => apiClient.get("/users/me"),
  updateMe: (data: Record<string, unknown>) => apiClient.patch("/users/me", data),
};

export const tasksApi: Record<string, Function> = {
  getUploadUrl: (filename: string, contentType: string, fileSizeBytes: number) =>
    apiClient.post("/tasks/upload-url", { filename, content_type: contentType, file_size_bytes: fileSizeBytes }),
  createTask: (data: {
    s3_key: string;
    original_filename: string;
    file_size_bytes: number;
    backend?: string;
    output_format?: string;
    language?: string;
    is_ocr?: boolean | null;
    enable_formula?: boolean;
    enable_table?: boolean;
    page_ranges?: string;
  }) => apiClient.post("/tasks/", data),
  batchGetUploadUrls: (files: { filename: string; content_type: string; file_size_bytes: number }[]) =>
    apiClient.post("/tasks/batch/upload-urls", files),
  batchCreateTasks: (tasks: {
    s3_key: string;
    original_filename: string;
    file_size_bytes: number;
    backend?: string;
    output_format?: string;
  }[]) => apiClient.post("/tasks/batch/tasks", tasks),
  list: (params?: { page?: number; page_size?: number; status?: string; keyword?: string }) =>
    apiClient.get("/tasks/", { params }),
  get: (id: string) => apiClient.get(`/tasks/${id}`),
  getResults: (id: string) => apiClient.get(`/tasks/${id}/results`),
  getPreview: (id: string) => apiClient.get(`/tasks/${id}/preview`),
  cancel: (id: string) => apiClient.delete(`/tasks/${id}`),
  delete: (id: string) => apiClient.delete(`/tasks/${id}`),
  retry: (id: string) => apiClient.post(`/tasks/${id}/retry`),
};

export const adminApi = {
  getStats: () => apiClient.get("/admin/stats"),
  listUsers: (params?: { page?: number; page_size?: number; search?: string; role?: string }) =>
    apiClient.get("/admin/users", { params }),
  getUser: (userId: string) => apiClient.get(`/admin/users/${userId}`),
  updateUser: (userId: string, data: { role?: string; is_active?: boolean; organization_id?: string }) =>
    apiClient.patch(`/admin/users/${userId}`, data),
  deleteUser: (userId: string) => apiClient.delete(`/admin/users/${userId}`),
  listTasks: (params?: { page?: number; page_size?: number; status?: string; user_id?: string; date_from?: string; date_to?: string }) =>
    apiClient.get("/admin/tasks", { params }),
};
