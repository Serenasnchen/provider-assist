/**
 * EdgeOne Edge Function: 通用 API 反向代理
 * 将所有 /api/* 请求转发到 Vercel 后端
 * 
 * 路径：edge-functions/api/[[default]].js
 * 匹配：所有 /api/* 路径
 */

const BACKEND_ORIGIN = 'https://provider-assist.vercel.app';

const CORS_HEADERS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'GET, POST, PUT, DELETE, OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type, Authorization',
  'Access-Control-Max-Age': '86400',
};

export default async function onRequest(context) {
  const { request } = context;
  const url = new URL(request.url);

  // 构造目标 URL：/api/question_list → https://provider-assist.vercel.app/api/question_list
  const targetUrl = `${BACKEND_ORIGIN}${url.pathname}${url.search}`;

  // 处理 OPTIONS 预检请求
  if (request.method === 'OPTIONS') {
    return new Response(null, { status: 204, headers: CORS_HEADERS });
  }

  // 构造转发请求头
  const proxyHeaders = new Headers(request.headers);
  proxyHeaders.set('Host', 'provider-assist.vercel.app');
  proxyHeaders.delete('cf-connecting-ip');
  proxyHeaders.delete('cf-ray');
  proxyHeaders.delete('x-forwarded-for');
  proxyHeaders.delete('x-real-ip');

  try {
    // 转发请求到 Vercel
    // eo.timeoutSetting 设置读取超时为 90 秒（默认 15 秒对知识库匹配接口不够）
    const response = await fetch(targetUrl, {
      method: request.method,
      headers: proxyHeaders,
      body: request.body,
      eo: {
        timeoutSetting: {
          connectTimeout: 15000,
          readTimeout: 90000,
          writeTimeout: 30000,
        }
      }
    });

    // 添加 CORS 头到响应
    const newHeaders = new Headers(response.headers);
    newHeaders.set('Access-Control-Allow-Origin', '*');
    newHeaders.set('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
    newHeaders.set('Access-Control-Allow-Headers', 'Content-Type, Authorization');

    return new Response(response.body, {
      status: response.status,
      headers: newHeaders,
    });
  } catch (error) {
    return new Response(
      JSON.stringify({ error: 'Proxy request failed', message: error.message }),
      {
        status: 502,
        headers: { 'Content-Type': 'application/json', ...CORS_HEADERS },
      }
    );
  }
}
