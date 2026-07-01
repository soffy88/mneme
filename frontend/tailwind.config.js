import colors from "tailwindcss/colors"

/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // 设计系统（沉静·镜子）：靛蓝主色 + 石板灰中性 + 语义强调
        primary: colors.indigo,
        accent: colors.sky,
      },
      fontFamily: {
        sans: [
          "system-ui", "-apple-system", '"Segoe UI"', "Roboto",
          '"PingFang SC"', '"Hiragino Sans GB"', '"Microsoft YaHei"', "sans-serif",
        ],
      },
      boxShadow: {
        card: "0 1px 2px rgba(15,23,42,0.04), 0 1px 3px rgba(15,23,42,0.06)",
        soft: "0 4px 16px rgba(15,23,42,0.06)",
      },
      borderRadius: {
        xl: "0.875rem",
        "2xl": "1.125rem",
      },
    },
  },
  plugins: [],
}
