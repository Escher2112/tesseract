// make_icon.swift — draws the 3D Terminal icon (a purple isometric cube with ">_" on its faces) as a 1024 px PNG. Lyra 2026-10-27.
import AppKit
let S: CGFloat = 1024
let img = NSImage(size: NSSize(width: S, height: S))
img.lockFocus()
let ctx = NSGraphicsContext.current!.cgContext
// background: dark rounded square (macOS icon grid: ~100 px margin)
let bg = NSBezierPath(roundedRect: NSRect(x: 100, y: 100, width: 824, height: 824), xRadius: 185, yRadius: 185)
NSGradient(colors: [NSColor(red: 0.13, green: 0.10, blue: 0.24, alpha: 1), NSColor(red: 0.04, green: 0.03, blue: 0.08, alpha: 1)])!.draw(in: bg, angle: -90)
// isometric cube
let c = CGPoint(x: 512, y: 500), r: CGFloat = 250
let top = CGPoint(x: c.x, y: c.y + r), bot = CGPoint(x: c.x, y: c.y - r)
let ul = CGPoint(x: c.x - r * 0.866, y: c.y + r / 2), ur = CGPoint(x: c.x + r * 0.866, y: c.y + r / 2)
let ll = CGPoint(x: c.x - r * 0.866, y: c.y - r / 2), lr = CGPoint(x: c.x + r * 0.866, y: c.y - r / 2)
func face(_ pts: [CGPoint], _ col: NSColor) {
    let p = NSBezierPath(); p.move(to: pts[0]); pts.dropFirst().forEach { p.line(to: $0) }; p.close()
    col.setFill(); p.fill()
    NSColor(red: 0.85, green: 0.78, blue: 1, alpha: 0.9).setStroke(); p.lineWidth = 7; p.lineJoinStyle = .round; p.stroke()
}
ctx.setShadow(offset: .zero, blur: 60, color: NSColor(red: 0.55, green: 0.4, blue: 1, alpha: 0.8).cgColor)
face([top, ur, c, ul], NSColor(red: 0.47, green: 0.36, blue: 0.86, alpha: 1))     // top
ctx.setShadow(offset: .zero, blur: 0, color: nil)
face([ul, c, bot, ll], NSColor(red: 0.27, green: 0.20, blue: 0.56, alpha: 1))     // left
face([c, ur, lr, bot], NSColor(red: 0.19, green: 0.14, blue: 0.42, alpha: 1))     // right
// ">_" on the two side faces, drawn as strokes in each face's own coordinates (u along its bottom edge, v up its side, both 0..1)
func prompt(on o: CGPoint, ex: CGVector, ey: CGVector) {
    func P(_ u: CGFloat, _ v: CGFloat) -> CGPoint { CGPoint(x: o.x + u * ex.dx + v * ey.dx, y: o.y + u * ex.dy + v * ey.dy) }
    let p = NSBezierPath()
    p.move(to: P(0.20, 0.68)); p.line(to: P(0.42, 0.50)); p.line(to: P(0.20, 0.32))   // >
    p.move(to: P(0.52, 0.30)); p.line(to: P(0.80, 0.30))                               // _
    NSColor(red: 0.78, green: 1, blue: 0.84, alpha: 1).setStroke(); p.lineWidth = 34; p.lineCapStyle = .round; p.lineJoinStyle = .round; p.stroke()
}
prompt(on: ll, ex: CGVector(dx: bot.x - ll.x, dy: bot.y - ll.y), ey: CGVector(dx: ul.x - ll.x, dy: ul.y - ll.y))   // left face
prompt(on: bot, ex: CGVector(dx: lr.x - bot.x, dy: lr.y - bot.y), ey: CGVector(dx: c.x - bot.x, dy: c.y - bot.y))  // right face
img.unlockFocus()
let rep = NSBitmapImageRep(data: img.tiffRepresentation!)!
try! rep.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: CommandLine.arguments[1]))
