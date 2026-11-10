// Apple's own Vision framework: no weights, nothing to download.
//   vision_tool cutout <in> <out.png>   the main subject on a transparent background
//   vision_tool faces <in>              JSON: for each face, five points in pixels (top left origin):
//                                       the two eyes, the nose, the two corners of the mouth
// Exit 3 means "nothing found" (no subject, no faces). The file is never touched.
import CoreImage
import Foundation
import Vision

func fail(_ message: String, _ code: Int32) -> Never {
    FileHandle.standardError.write((message + "\n").data(using: .utf8)!)
    exit(code)
}

func centre(_ points: [CGPoint]) -> CGPoint {
    let n = CGFloat(points.count)
    return CGPoint(x: points.reduce(0) { $0 + $1.x } / n, y: points.reduce(0) { $0 + $1.y } / n)
}

let args = CommandLine.arguments
guard args.count >= 3 else { fail("usage: vision_tool cutout|faces <in> [out.png]", 2) }
let url = URL(fileURLWithPath: args[2])
guard let image = CIImage(contentsOf: url, options: [.applyOrientationProperty: true]) else {
    fail("could not read the picture", 2)
}
let handler = VNImageRequestHandler(ciImage: image)

do {
    switch args[1] {
    case "cutout":
        guard args.count == 4 else { fail("usage: vision_tool cutout <in> <out.png>", 2) }
        let request = VNGenerateForegroundInstanceMaskRequest()
        try handler.perform([request])
        guard let result = request.results?.first else { fail("no subject found", 3) }
        let masked = try result.generateMaskedImage(ofInstances: result.allInstances, from: handler,
                                                    croppedToInstancesExtent: false)
        let picture = CIImage(cvPixelBuffer: masked)
        try CIContext().writePNGRepresentation(of: picture, to: URL(fileURLWithPath: args[3]), format: .RGBA8,
                                               colorSpace: CGColorSpace(name: CGColorSpace.sRGB)!)
    case "faces":
        let request = VNDetectFaceLandmarksRequest()
        try handler.perform([request])
        let size = CGSize(width: image.extent.width, height: image.extent.height)
        var faces: [[[Double]]] = []
        for face in request.results ?? [] {
            guard let marks = face.landmarks, let le = marks.leftEye, let re = marks.rightEye,
                  let nose = marks.nose, let lips = marks.outerLips else { continue }
            var eyes = [centre(le.pointsInImage(imageSize: size)), centre(re.pointsInImage(imageSize: size))]
            eyes.sort { $0.x < $1.x }
            let mouth = lips.pointsInImage(imageSize: size).sorted { $0.x < $1.x }
            let points = [eyes[0], eyes[1], centre(nose.pointsInImage(imageSize: size)), mouth.first!, mouth.last!]
            faces.append(points.map { [Double($0.x), Double(size.height - $0.y)] })
        }
        guard !faces.isEmpty else { fail("no faces found", 3) }
        print(String(data: try JSONSerialization.data(withJSONObject: faces), encoding: .utf8)!)
    default:
        fail("unknown command", 2)
    }
} catch {
    fail("vision failed: \(error)", 1)
}
