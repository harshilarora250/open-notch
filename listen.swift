// listen.swift - on-device speech recognition helper for notch.py (macOS only)
//
// Prints one JSON object per line on stdout:
//   {"event":"ready"}                 microphone is live
//   {"event":"reset"}                 a new recognition session started
//   {"text":"words heard so far"}     partial transcript (cumulative per session)
//   {"error":"message"}               something went wrong
//
// Usage: listen [locale]     e.g. listen en-US

import Foundation
import Speech
import AVFoundation

setvbuf(stdout, nil, _IOLBF, 0)

func emit(_ dict: [String: Any]) {
    guard let data = try? JSONSerialization.data(withJSONObject: dict),
          let line = String(data: data, encoding: .utf8) else { return }
    print(line)
    fflush(stdout)
}

final class Listener {
    private let recognizer: SFSpeechRecognizer
    private let engine = AVAudioEngine()
    private var request: SFSpeechAudioBufferRecognitionRequest?
    private var task: SFSpeechRecognitionTask?
    private var generation = 0
    private let lock = NSLock()

    init?(localeID: String) {
        guard let r = SFSpeechRecognizer(locale: Locale(identifier: localeID)) else { return nil }
        recognizer = r
    }

    func start() {
        guard recognizer.isAvailable else {
            emit(["error": "Speech recognizer is not available for this language right now."])
            exit(1)
        }
        let input = engine.inputNode
        let format = input.outputFormat(forBus: 0)
        input.installTap(onBus: 0, bufferSize: 2048, format: format) { [weak self] buffer, _ in
            guard let self = self else { return }
            self.lock.lock()
            let req = self.request
            self.lock.unlock()
            req?.append(buffer)
        }
        engine.prepare()
        do {
            try engine.start()
        } catch {
            emit(["error": "Could not start audio engine: \(error.localizedDescription)"])
            exit(1)
        }
        beginTask()
        // Recognition sessions can expire, so roll over to a fresh one regularly.
        Timer.scheduledTimer(withTimeInterval: 50, repeats: true) { [weak self] _ in
            self?.beginTask()
        }
        emit(["event": "ready"])
    }

    func beginTask() {
        lock.lock()
        generation += 1
        let gen = generation
        request?.endAudio()
        task?.cancel()
        let req = SFSpeechAudioBufferRecognitionRequest()
        req.shouldReportPartialResults = true
        if recognizer.supportsOnDeviceRecognition {
            req.requiresOnDeviceRecognition = true   // audio stays on this Mac
        }
        request = req
        lock.unlock()

        emit(["event": "reset"])

        let newTask = recognizer.recognitionTask(with: req) { [weak self] result, error in
            guard let self = self else { return }
            self.lock.lock()
            let isCurrent = (gen == self.generation)
            self.lock.unlock()
            guard isCurrent else { return }

            if let result = result {
                emit(["text": result.bestTranscription.formattedString])
            }
            if error != nil || (result?.isFinal ?? false) {
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) { self.beginTask() }
            }
        }
        lock.lock()
        task = newTask
        lock.unlock()
    }
}

let localeID = CommandLine.arguments.count > 1 ? CommandLine.arguments[1] : "en-US"

guard let listener = Listener(localeID: localeID) else {
    emit(["error": "Unsupported language: \(localeID)"])
    exit(1)
}

SFSpeechRecognizer.requestAuthorization { status in
    guard status == .authorized else {
        emit(["error": "Speech Recognition permission denied. Enable it for your terminal in System Settings > Privacy & Security > Speech Recognition."])
        exit(1)
    }
    AVCaptureDevice.requestAccess(for: .audio) { granted in
        guard granted else {
            emit(["error": "Microphone permission denied. Enable it for your terminal in System Settings > Privacy & Security > Microphone."])
            exit(1)
        }
        DispatchQueue.main.async { listener.start() }
    }
}

RunLoop.main.run()