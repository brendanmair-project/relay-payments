// ESLint flat config (ADR-0007): Next.js core web vitals and TypeScript rules.
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const config = [...nextVitals, ...nextTs, { ignores: [".next/**", "node_modules/**", "next-env.d.ts"] }];

export default config;
