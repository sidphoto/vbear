// Draws the VBear icon (a white V on a black rounded square, after the
// Formosan black bear's chest mark) into an .iconset for iconutil.
import AppKit

let out = CommandLine.arguments.count > 1 ? CommandLine.arguments[1] : "AppIcon.iconset"
try? FileManager.default.createDirectory(atPath: out, withIntermediateDirectories: true)

func render(_ px: Int) -> Data {
    let s = CGFloat(px)
    let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: px, pixelsHigh: px, bitsPerSample: 8,
                               samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
                               colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
    let inset = s * 0.09  // macOS icon grid margin
    let body = NSRect(x: inset, y: inset, width: s - 2 * inset, height: s - 2 * inset)
    NSColor(calibratedRed: 0.114, green: 0.114, blue: 0.106, alpha: 1).setFill()
    NSBezierPath(roundedRect: body, xRadius: body.width * 0.225, yRadius: body.width * 0.225).fill()
    let v = NSBezierPath()
    v.move(to: NSPoint(x: body.minX + body.width * 0.25, y: body.minY + body.height * 0.70))
    v.line(to: NSPoint(x: body.midX, y: body.minY + body.height * 0.27))
    v.line(to: NSPoint(x: body.minX + body.width * 0.75, y: body.minY + body.height * 0.70))
    v.lineWidth = body.width * 0.11
    v.lineCapStyle = .round
    v.lineJoinStyle = .round
    NSColor(calibratedRed: 0.953, green: 0.937, blue: 0.894, alpha: 1).setStroke()
    v.stroke()
    NSGraphicsContext.restoreGraphicsState()
    return rep.representation(using: .png, properties: [:])!
}

for base in [16, 32, 128, 256, 512] {
    for scale in [1, 2] {
        let name = scale == 1 ? "icon_\(base)x\(base).png" : "icon_\(base)x\(base)@2x.png"
        try! render(base * scale).write(to: URL(fileURLWithPath: out).appendingPathComponent(name))
    }
}
