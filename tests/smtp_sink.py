"""Tiny SMTP server for tests: accepts mail on localhost and appends each message to a file."""
import socketserver, sys


class H(socketserver.StreamRequestHandler):
    def w(self, s):
        self.wfile.write((s + "\r\n").encode())

    def handle(self):
        self.w("220 sink ready")
        data, in_data = [], False
        for raw in self.rfile:
            line = raw.decode("utf-8", "replace").rstrip("\r\n")
            if in_data:
                if line == ".":
                    in_data = False
                    with open(self.server.out, "a") as f:
                        f.write("\n".join(data) + "\n=====\n")
                    data = []; self.w("250 queued")
                else:
                    data.append(line[1:] if line.startswith("..") else line)
                continue
            cmd = line.split(" ")[0].upper()
            if cmd in ("EHLO", "HELO"):
                self.w("250 sink")
            elif cmd == "DATA":
                in_data = True; self.w("354 go")
            elif cmd == "QUIT":
                self.w("221 bye"); return
            else:
                self.w("250 ok")


if __name__ == "__main__":
    srv = socketserver.ThreadingTCPServer(("127.0.0.1", int(sys.argv[1])), H)
    srv.out = sys.argv[2]
    srv.serve_forever()
