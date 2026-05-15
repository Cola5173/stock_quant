/**
 * 后端连接配置
 *
 * 修改这里即可指向不同的后端服务（开发/远端部署等）。
 * 也支持通过环境变量 NEXT_PUBLIC_API_BASE 覆盖（重启 dev server 生效）。
 */

const DEFAULT_API_HOST = "127.0.0.1";
const DEFAULT_API_PORT = 7088;

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ?? `http://${DEFAULT_API_HOST}:${DEFAULT_API_PORT}`;
