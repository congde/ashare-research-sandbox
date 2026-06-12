import { render, screen } from "@testing-library/react";
import GlowCard from "../../components/GlowCard";

describe("GlowCard", () => {
  it("renders with title and children", () => {
    render(<GlowCard title="Test Title">Hello World</GlowCard>);
    expect(screen.getByText("Test Title")).toBeInTheDocument();
    expect(screen.getByText("Hello World")).toBeInTheDocument();
  });

  it("renders children without title", () => {
    render(<GlowCard>Content Only</GlowCard>);
    expect(screen.getByText("Content Only")).toBeInTheDocument();
    // No header should be rendered when title is not provided
    expect(screen.queryByText("Test Title")).not.toBeInTheDocument();
  });

  it.each(["blue", "cyan", "purple", "green"] as const)(
    "applies glow-border-%s class for color=%s",
    (color) => {
      const { container } = render(
        <GlowCard color={color} title={`Card ${color}`}>
          body
        </GlowCard>,
      );
      const card = container.firstChild as HTMLElement;
      expect(card.className).toContain(`glow-border-${color}`);
      expect(card.className).toContain("tech-panel");
    },
  );

  it("defaults to blue color when no color prop provided", () => {
    const { container } = render(<GlowCard>default</GlowCard>);
    const card = container.firstChild as HTMLElement;
    expect(card.className).toContain("glow-border-blue");
  });

  it("renders extra slot content alongside the title", () => {
    render(
      <GlowCard title="Main Title" extra={<span>Extra Info</span>}>
        body
      </GlowCard>,
    );
    expect(screen.getByText("Main Title")).toBeInTheDocument();
    expect(screen.getByText("Extra Info")).toBeInTheDocument();
  });

  it("does not render extra when only title is provided", () => {
    render(<GlowCard title="Only Title">body</GlowCard>);
    expect(screen.getByText("Only Title")).toBeInTheDocument();
    // extra wrapper should not exist
    const titleEl = screen.getByText("Only Title");
    const header = titleEl.closest(".glow-card-header");
    expect(header).toBeInTheDocument();
    // There should be no sibling with extra content
    expect(screen.queryByText("Extra Info")).not.toBeInTheDocument();
  });

  it("applies custom style to the outer container", () => {
    const { container } = render(
      <GlowCard style={{ marginTop: 20, padding: 10 }}>styled</GlowCard>,
    );
    const card = container.firstChild as HTMLElement;
    expect(card.style.marginTop).toBe("20px");
    expect(card.style.padding).toBe("10px");
  });

  it("applies custom bodyStyle to the body div", () => {
    const { container } = render(
      <GlowCard bodyStyle={{ padding: 32, color: "red" }}>body content</GlowCard>,
    );
    const body = container.querySelector(".glow-card-body") as HTMLElement;
    expect(body.style.padding).toBe("32px");
    expect(body.style.color).toBe("red");
  });

  it("applies custom className alongside default classes", () => {
    const { container } = render(
      <GlowCard className="my-custom-class">custom</GlowCard>,
    );
    const card = container.firstChild as HTMLElement;
    expect(card.className).toContain("my-custom-class");
    expect(card.className).toContain("glow-border-blue");
    expect(card.className).toContain("tech-panel");
  });

  it("calls onClick handler when card is clicked", () => {
    const handleClick = vi.fn();
    const { container } = render(
      <GlowCard onClick={handleClick}>clickable</GlowCard>,
    );
    (container.firstChild as HTMLElement).click();
    expect(handleClick).toHaveBeenCalledTimes(1);
  });
});
