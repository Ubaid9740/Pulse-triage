// Line icons drawn with react-native-svg (already a dependency through react-native-qrcode-svg),
// the same 24px / 2px-stroke set the command dashboard uses. No icon package needed.
import Svg, { Path } from "react-native-svg";

const circle = (cx, cy, r) => `M${cx - r} ${cy}a${r} ${r} 0 1 0 ${r * 2} 0a${r} ${r} 0 1 0 ${-r * 2} 0`;

const PATHS = {
  alert: ["m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3z", "M12 9v4", "M12 17h.01"],
  bell: ["M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9", "M10.3 21a1.94 1.94 0 0 0 3.4 0"],
  lifebuoy: [circle(12, 12, 10), circle(12, 12, 4), "m4.93 4.93 4.24 4.24", "m14.83 9.17 4.24-4.24", "m14.83 14.83 4.24 4.24", "m9.17 14.83-4.24 4.24"],
  navigation: ["M3 11l19-9-9 19-2-8-8-2z"],
  userCheck: [circle(9, 7, 4), "M2 21v-2a4 4 0 0 1 4-4h6a4 4 0 0 1 4 4v2", "m16 11 2 2 4-4"],
  user: [circle(12, 8, 4), "M20 21a8 8 0 0 0-16 0"],
  users: ["M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2", circle(9, 7, 4), "M22 21v-2a4 4 0 0 0-3-3.87", "M16 3.13a4 4 0 0 1 0 7.75"],
  qr: ["M3 3h7v7H3z", "M14 3h7v7h-7z", "M3 14h7v7H3z", "M14 14h3v3h-3z", "M21 14v.01", "M14 21h.01", "M17 21h4v-4"],
  scan: ["M3 7V5a2 2 0 0 1 2-2h2", "M17 3h2a2 2 0 0 1 2 2v2", "M21 17v2a2 2 0 0 1-2 2h-2", "M7 21H5a2 2 0 0 1-2-2v-2", "M7 12h10"],
  settings: ["M21 4h-7", "M10 4H3", "M21 12h-9", "M8 12H3", "M21 20h-5", "M12 20H3", "M14 2v4", "M8 10v4", "M16 18v4"],
  chevronRight: ["m9 18 6-6-6-6"],
  chevronLeft: ["m15 18-6-6 6-6"],
  wifi: ["M5 12.55a11 11 0 0 1 14.08 0", "M1.42 9a16 16 0 0 1 21.16 0", "M8.53 16.11a6 6 0 0 1 6.95 0", "M12 20h.01"],
  wifiOff: ["M2 2l20 20", "M8.5 16.5a5 5 0 0 1 7 0", "M12 20h.01", "M5 12.86a10 10 0 0 1 5.17-2.69", "M19 12.86a10 10 0 0-2.1-1.5", "M2 8.82a15 15 0 0 1 4.17-2.65", "M10.66 5c4.01-.36 8.14.9 11.34 3.76"],
  refresh: ["M21 12a9 9 0 0 0-9-9 9.75 9.75 0 0 0-6.74 2.74L3 8", "M3 3v5h5", "M3 12a9 9 0 0 0 9 9 9.75 9.75 0 0 0 6.74-2.74L21 16", "M16 16h5v5"],
  check: ["M20 6 9 17l-5-5"],
  x: ["M18 6 6 18", "M6 6l12 12"],
  mapPin: ["M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0z", circle(12, 10, 3)],
  crosshair: [circle(12, 12, 10), "M22 12h-4", "M6 12H2", "M12 6V2", "M12 22v-4"],
  volume: ["M11 5 6 9H2v6h4l5 4V5z", "M15.54 8.46a5 5 0 0 1 0 7.07", "M19.07 4.93a10 10 0 0 1 0 14.14"],
  shield: ["M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z", "m9 12 2 2 4-4"],
  clock: [circle(12, 12, 10), "M12 6v6l4 2"],
  home: ["m3 9 9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z", "M9 22V12h6v10"],
  power: ["M12 2v10", "M18.4 6.6a9 9 0 1 1-12.77.04"],
  camera: ["M14.5 4h-5L7 7H4a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-3l-2.5-3z", circle(12, 13, 3)],
  send: ["M22 2 11 13", "M22 2l-7 20-4-9-9-4 20-7z"],
  info: [circle(12, 12, 10), "M12 16v-4", "M12 8h.01"],
  lock: ["M5 11h14v10H5z", "M7 11V7a5 5 0 0 1 10 0v4"],
  ban: [circle(12, 12, 10), "m4.9 4.9 14.2 14.2"],
  minus: ["M5 12h14"],
  plus: ["M12 5v14", "M5 12h14"],
  search: [circle(11, 11, 8), "m21 21-4.3-4.3"],
  heart: ["M19 14c1.49-1.46 3-3.21 3-5.5A5.5 5.5 0 0 0 16.5 3c-1.76 0-3 .5-4.5 2-1.5-1.5-2.74-2-4.5-2A5.5 5.5 0 0 0 2 8.5c0 2.3 1.5 4.05 3 5.5l7 7z"],
  fuel: ["M3 22h12", "M4 9h10", "M14 22V4a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v18", "M14 13h2a2 2 0 0 1 2 2v2a2 2 0 0 0 4 0V9.83a2 2 0 0 0-.59-1.42L18 5"],
  link: ["M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71", "M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"],
  bluetooth: ["m7 7 10 10-5 5V2l5 5L7 17"],
  edit: ["M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5z"]
};

export default function Icon({ name, size = 20, color = "#0F1B2D", strokeWidth = 2 }) {
  return (
    <Svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth}
    strokeLinecap="round" strokeLinejoin="round" accessibilityElementsHidden importantForAccessibility="no-hide-descendants">
      {(PATHS[name] || []).map((d, i) => <Path key={i} d={d} />)}
    </Svg>);

}
