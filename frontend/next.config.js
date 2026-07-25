const path = require("path");

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // 根目录也有 package-lock 时，固定 frontend 为 tracing root，消除误报
  outputFileTracingRoot: path.join(__dirname),
};

module.exports = nextConfig;
