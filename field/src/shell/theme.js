// Design tokens shared with the Pulse command dashboard, so the
// phone and the command post read as one product. Light, calm surfaces; red only means danger.
export const T = {
  bg: "#F2F4F7",
  panel: "#FFFFFF",
  panel2: "#F7F9FB",
  panel3: "#EDF1F5",
  ink: "#0F1B2D",
  ink2: "#2B3A4F",
  muted: "#566275",
  faint: "#8692A3",
  line: "#E3E8EF",
  lineStrong: "#CBD3DE",

  primary: "#1D4AB8",
  primaryDark: "#173E9C",
  primarySoft: "#EAF0FC",
  primaryLine: "#BCCDF1",

  red: "#C4231B", // text on white
  redFill: "#D92D20", // fills (white text)
  redSoft: "#FDEDEC",
  redLine: "#F4C7C3",
  orange: "#B54708",
  orangeFill: "#EF7B1A", // fills (dark text)
  orangeSoft: "#FFF2E5",
  yellow: "#7A5A00",
  yellowFill: "#F4C534", // fills (dark text)
  yellowSoft: "#FEF7D6",
  green: "#157A44",
  greenSoft: "#E7F5EC",
  greenLine: "#B9DFC9",
  amber: "#9A5B05",
  amberSoft: "#FEF4DC",
  amberLine: "#F2D38A"
};

export const RADIUS = { sm: 8, md: 12, lg: 16 };

// Tones used by pills, notices and status rows: [text/icon colour, background, border].
export const TONES = {
  neutral: [T.ink2, T.panel3, T.line],
  info: [T.primary, T.primarySoft, T.primaryLine],
  success: [T.green, T.greenSoft, T.greenLine],
  warning: [T.amber, T.amberSoft, T.amberLine],
  critical: [T.red, T.redSoft, T.redLine]
};
