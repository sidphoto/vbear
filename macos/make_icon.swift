// Draws the VBear icon (the pixel Formosan black bear with the white V on its chest) into an .iconset for iconutil.
// The pixels live in AppIcon.pixels.json: icon16 (16 x 16) for the 16 and 32 pixel sizes, rows (32 x 32) for 64 and up.
// Every bear cell is a whole number of pixels with hard edges; the grid is centred on the rounded plate.
// With `--layer <file.png>` after the two paths it writes one picture instead: the bear alone, 1024 x 1024, 32 pixels a
// cell, on a transparent ground. That is the layer of the Icon Composer .icon (macos/AppIcon.icon); the system draws the plate.
import AppKit

let out = CommandLine.arguments.count > 1 ? CommandLine.arguments[1] : "AppIcon.iconset"
let dataPath = CommandLine.arguments.count > 2 ? CommandLine.arguments[2] : "macos/AppIcon.pixels.json"
let layerPath: String? = CommandLine.arguments.count > 4 && CommandLine.arguments[3] == "--layer" ? CommandLine.arguments[4] : nil
if layerPath == nil { try? FileManager.default.createDirectory(atPath: out, withIntermediateDirectories: true) }

guard let raw = try? Data(contentsOf: URL(fileURLWithPath: dataPath)),
      let json = try? JSONSerialization.jsonObject(with: raw) as? [String: Any],
      let rows = json["rows"] as? [String], let icon16 = json["icon16"] as? [String],
      let palette = json["palette"] as? [String: Any], let backgroundKey = json["iconBackground"] as? String
else { fatalError("cannot read \(dataPath)") }

func color(_ key: Character) -> NSColor? {
    guard let hex = palette[String(key)] as? String, hex.count == 7 else { return nil }
    let v = UInt32(hex.dropFirst(), radix: 16)!
    return NSColor(deviceRed: CGFloat((v >> 16) & 255) / 255, green: CGFloat((v >> 8) & 255) / 255,
                   blue: CGFloat(v & 255) / 255, alpha: 1)
}
let background = color(Character(backgroundKey))!

func render(_ px: Int) -> Data {
    let s = CGFloat(px)
    let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: px, pixelsHigh: px, bitsPerSample: 8,
                               samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
                               colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
    NSGraphicsContext.saveGraphicsState()
    let gc = NSGraphicsContext(bitmapImageRep: rep)!
    NSGraphicsContext.current = gc
    gc.shouldAntialias = false  // only whole-pixel squares are drawn below, except the plate on the large sizes
    // Cells are counted from the top row down; AppKit's y axis points up.
    func cell(_ x: Int, _ y: Int, _ size: Int, _ originX: Int, _ originY: Int, _ fill: NSColor) {
        fill.setFill()
        NSRect(x: originX + x * size, y: px - originY - (y + 1) * size, width: size, height: size).fill()
    }
    if px <= 32 {
        // 16 x 16 grid, 1 or 2 pixels a cell. The plate is made of cells too: the margin and the corner follow
        // the usual proportions (9% margin, 0.225 radius), rounded to cells, so nothing is blurred.
        let n = icon16.count, size = px / n
        let inset = (CGFloat(n) * 0.09).rounded(), body = CGFloat(n) - 2 * inset, radius = body * 0.225
        for (y, row) in icon16.enumerated() {
            for (x, ch) in row.enumerated() {
                if let c = color(ch) { cell(x, y, size, 0, 0, c); continue }
                let dx = CGFloat(x) + 0.5 - inset, dy = CGFloat(y) + 0.5 - inset
                let cx = max(radius, min(body - radius, dx)), cy = max(radius, min(body - radius, dy))
                if dx >= 0 && dy >= 0 && dx < body && dy < body && (dx - cx) * (dx - cx) + (dy - cy) * (dy - cy) <= radius * radius {
                    cell(x, y, size, 0, 0, background)
                }
            }
        }
    } else {
        // 32 x 32 grid. The plate keeps the old proportions (9% margin, 0.225 radius). The whole grid is meant to
        // fit the plate (the bear itself has empty cells around it), so a cell is the plate's width over 32, rounded
        // to a whole number of pixels, and the grid sits in the middle.
        let inset = s * 0.09
        let body = NSRect(x: inset, y: inset, width: s - 2 * inset, height: s - 2 * inset)
        gc.shouldAntialias = true
        background.setFill()
        NSBezierPath(roundedRect: body, xRadius: body.width * 0.225, yRadius: body.width * 0.225).fill()
        gc.shouldAntialias = false
        let n = rows.count, size = max(1, Int((body.width / CGFloat(rows.count)).rounded()))
        let origin = (px - n * size) / 2
        for (y, row) in rows.enumerated() {
            for (x, ch) in row.enumerated() {
                if let c = color(ch) { cell(x, y, size, origin, origin, c) }
            }
        }
    }
    NSGraphicsContext.restoreGraphicsState()
    return rep.representation(using: .png, properties: [:])!
}

// The bear's own cells, no plate: what the .icon layer shows over the plate colour the .icon document names.
func renderLayer() -> Data {
    let n = rows.count, size = 1024 / n
    let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: n * size, pixelsHigh: n * size, bitsPerSample: 8,
                               samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
                               colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
    NSGraphicsContext.saveGraphicsState()
    let gc = NSGraphicsContext(bitmapImageRep: rep)!
    NSGraphicsContext.current = gc
    gc.shouldAntialias = false
    for (y, row) in rows.enumerated() {
        for (x, ch) in row.enumerated() {
            guard let c = color(ch) else { continue }
            c.setFill()
            NSRect(x: x * size, y: (n - 1 - y) * size, width: size, height: size).fill()
        }
    }
    NSGraphicsContext.restoreGraphicsState()
    return rep.representation(using: .png, properties: [:])!
}

if let layerPath = layerPath {
    precondition(rows.count > 0 && 1024 % rows.count == 0, "the grid must divide 1024 into whole pixels")
    try! renderLayer().write(to: URL(fileURLWithPath: layerPath))
    exit(0)
}

for base in [16, 32, 128, 256, 512] {
    for scale in [1, 2] {
        let name = scale == 1 ? "icon_\(base)x\(base).png" : "icon_\(base)x\(base)@2x.png"
        try! render(base * scale).write(to: URL(fileURLWithPath: out).appendingPathComponent(name))
    }
}
