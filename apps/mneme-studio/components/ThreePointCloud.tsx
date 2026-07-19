"use client";

// ThreePointCloud —— W4 Visualize：react-three-fiber 首次真实投用（此前
// package.json 里装了但零页面使用）。渲染 kernel_to_three 产出的真实
// (x,y,z) 点云数据——纯客户端渲染，数据本身在服务端就已经是普通数字数组
// （非可执行内容），这里只是把数字数组变成 WebGL 几何体，零执行风险（VZ-3）。

import { Canvas } from "@react-three/fiber";
import { OrbitControls, PointMaterial, Points } from "@react-three/drei";

export function ThreePointCloud({
  points,
}: {
  points: { x: number[]; y: number[]; z: number[] };
}) {
  const n = points.x.length;
  const positions = new Float32Array(n * 3);
  for (let i = 0; i < n; i++) {
    positions[i * 3] = points.x[i];
    positions[i * 3 + 1] = points.z[i]; // three.js 里 y 是竖直轴，用 z（高度）填 y
    positions[i * 3 + 2] = points.y[i];
  }

  return (
    <div style={{ width: "100%", height: 360 }} data-testid="three-canvas">
      <Canvas camera={{ position: [12, 12, 12], fov: 50 }}>
        <ambientLight intensity={0.8} />
        <pointLight position={[10, 10, 10]} />
        <Points positions={positions} stride={3}>
          <PointMaterial
            transparent
            color="#2563EB"
            size={0.15}
            sizeAttenuation
            depthWrite={false}
          />
        </Points>
        <OrbitControls enableDamping />
      </Canvas>
    </div>
  );
}
