import { render, screen } from "@testing-library/react";
import ProgressRing from "../../components/ProgressRing";

describe("ProgressRing", () => {
  it("renders with percent and label", () => {
    render(<ProgressRing percent={75} label="CPU" />);
    expect(screen.getByText("75%")).toBeInTheDocument();
    expect(screen.getByText("CPU")).toBeInTheDocument();
  });

  it("renders SVG circle elements", () => {
    const { container } = render(<ProgressRing percent={50} />);
    const svg = container.querySelector("svg");
    expect(svg).toBeInTheDocument();
    // Two circles: track (background) + progress (foreground)
    const circles = container.querySelectorAll("circle");
    expect(circles.length).toBe(2);
  });

  it("renders title when provided", () => {
    render(<ProgressRing percent={60} title="Completion Rate" />);
    expect(screen.getByText("Completion Rate")).toBeInTheDocument();
    expect(screen.getByText("60%")).toBeInTheDocument();
  });

  it("does not render title div when title is not provided", () => {
    const { container } = render(<ProgressRing percent={40} />);
    // The only text content should be the percent inside the SVG
    expect(screen.getByText("40%")).toBeInTheDocument();
    // No title div outside the SVG
    const divs = container.querySelectorAll("div");
    // Only the wrapper div exists
    expect(divs.length).toBe(1);
  });

  it("does not render label text when label is not provided", () => {
    const { container } = render(<ProgressRing percent={30} />);
    const textElements = container.querySelectorAll("text");
    // Only the percent text, no label text
    expect(textElements.length).toBe(1);
    expect(textElements[0].textContent).toBe("30%");
  });

  it("applies different color to the progress circle stroke", () => {
    const { container } = render(<ProgressRing percent={80} color="#ff0000" />);
    const circles = container.querySelectorAll("circle");
    // Second circle is the progress arc
    const progressCircle = circles[1];
    expect(progressCircle.getAttribute("stroke")).toBe("#ff0000");
  });

  it("applies color to the percent text fill", () => {
    const { container } = render(<ProgressRing percent={55} color="#00ff00" />);
    const percentText = container.querySelector("text");
    expect(percentText?.getAttribute("fill")).toBe("#00ff00");
  });

  it("uses default color #22d3ee when no color prop provided", () => {
    const { container } = render(<ProgressRing percent={10} />);
    const circles = container.querySelectorAll("circle");
    const progressCircle = circles[1];
    expect(progressCircle.getAttribute("stroke")).toBe("#22d3ee");
  });

  it("applies custom size to the SVG element", () => {
    const { container } = render(<ProgressRing percent={42} size={120} />);
    const svg = container.querySelector("svg");
    expect(svg?.getAttribute("width")).toBe("120");
    expect(svg?.getAttribute("height")).toBe("120");
  });

  it("clamps percent to 0 when given a negative value", () => {
    render(<ProgressRing percent={-10} />);
    expect(screen.getByText("0%")).toBeInTheDocument();
  });

  it("clamps percent to 100 when given a value above 100", () => {
    render(<ProgressRing percent={150} />);
    expect(screen.getByText("100%")).toBeInTheDocument();
  });

  it("renders both label and title together", () => {
    render(<ProgressRing percent={88} label="Score" title="Agent Rating" />);
    expect(screen.getByText("88%")).toBeInTheDocument();
    expect(screen.getByText("Score")).toBeInTheDocument();
    expect(screen.getByText("Agent Rating")).toBeInTheDocument();
  });
});
