//! A minimal HTTP/1.1 client over std::net.
//!
//! WHY NOT A CRATE. The relay speaks plain http on its own port, so the only thing an HTTP crate would
//! add here is TLS — and TLS is what turns a Windows cross-build from one command into a project
//! (vendored OpenSSL, or rustls plus a certificate store). This is sixty lines, has no build
//! requirements on any target, and its failure modes are visible.
//!
//! It is NOT a general-purpose client: no redirects, no chunked-encoding edge cases beyond the one the
//! node emits, no connection reuse. It talks to one relay.

use std::io::{Read, Write};
use std::net::{TcpStream, ToSocketAddrs};
use std::time::Duration;

pub struct Relay {
    pub host: String,
    pub port: u16,
}

impl Relay {
    /// Parse `host`, `host:port`, or `http://host:port`, defaulting to the node port.
    pub fn parse(s: &str) -> Result<Relay, String> {
        Relay::parse_with_default(s, 9173)
    }

    /// THE DEFAULT PORT IS NOT UNIVERSAL. A relay lives on 9173 and an arbitrary http:// URL lives on
    /// 80, and defaulting a vendor's certificate host to 9173 does not fail — it HANGS, connecting to a
    /// port nothing answers on, which presents as the program freezing rather than as a wrong address.
    pub fn parse_with_default(s: &str, default_port: u16) -> Result<Relay, String> {
        let s = s.trim().trim_start_matches("http://").trim_end_matches('/');
        let (host, port) = match s.rsplit_once(':') {
            Some((h, p)) => (h.to_string(), p.parse::<u16>().map_err(|_| "bad port")?),
            None => (s.to_string(), default_port),
        };
        if host.is_empty() {
            return Err("relay host is empty".into());
        }
        Ok(Relay { host, port })
    }

    pub fn get(&self, path: &str) -> Result<String, String> {
        self.request("GET", path, None)
    }

    /// A GET whose body is BINARY. Certificates are DER, and routing them through the text path
    /// replaces every invalid UTF-8 byte with U+FFFD — which corrupts the certificate silently and
    /// presents as a parse failure somewhere far away.
    pub fn get_bytes(&self, path: &str) -> Result<Vec<u8>, String> {
        let raw = self.request_raw("GET", path, None)?;
        let sep = b"\r\n\r\n";
        let pos = raw.windows(4).position(|w| w == sep)
            .ok_or("malformed response (no header terminator)")?;
        Ok(raw[pos + 4..].to_vec())
    }

    pub fn post_json(&self, path: &str, body: &str) -> Result<String, String> {
        self.request("POST", path, Some(body))
    }

    fn request(&self, method: &str, path: &str, body: Option<&str>) -> Result<String, String> {
        let raw = self.request_raw(method, path, body)?;
        self.finish_text(&raw)
    }

    fn request_raw(&self, method: &str, path: &str, body: Option<&str>) -> Result<Vec<u8>, String> {
        let addr = format!("{}:{}", self.host, self.port);
        // CONNECT WITH A DEADLINE. A plain TcpStream::connect to a host that drops packets waits for
        // the OS default, which is minutes — long enough that a user reasonably concludes the program
        // has hung, and a vendor endpoint that is merely unreachable should not look like a crash.
        let deadline = Duration::from_secs(10);
        let mut stream = addr
            .to_socket_addrs()
            .map_err(|e| format!("resolve {addr}: {e}"))?
            .find_map(|sa| TcpStream::connect_timeout(&sa, deadline).ok())
            .ok_or_else(|| format!("connect {addr}: unreachable"))?;
        stream.set_read_timeout(Some(Duration::from_secs(20))).ok();
        stream.set_write_timeout(Some(Duration::from_secs(20))).ok();

        let mut req = format!(
            "{method} {path} HTTP/1.1\r\nHost: {}\r\nConnection: close\r\nUser-Agent: nado-tpm-attest\r\n",
            self.host
        );
        if let Some(b) = body {
            req.push_str("Content-Type: application/json\r\n");
            req.push_str(&format!("Content-Length: {}\r\n", b.len()));
        }
        req.push_str("\r\n");
        if let Some(b) = body {
            req.push_str(b);
        }
        stream.write_all(req.as_bytes()).map_err(|e| format!("write: {e}"))?;

        let mut raw = Vec::new();
        stream.read_to_end(&mut raw).map_err(|e| format!("read: {e}"))?;
        Ok(raw)
    }

    fn finish_text(&self, raw: &[u8]) -> Result<String, String> {
        let text = String::from_utf8_lossy(raw).into_owned();
        let (head, rest) = text
            .split_once("\r\n\r\n")
            .ok_or_else(|| "malformed response (no header terminator)".to_string())?;

        let status: u16 = head
            .lines()
            .next()
            .and_then(|l| l.split_whitespace().nth(1))
            .and_then(|c| c.parse().ok())
            .ok_or_else(|| "malformed status line".to_string())?;

        // The node closes the connection, so a chunked body still arrives whole; de-chunk it when the
        // header says so rather than handing the caller size markers it would parse as JSON.
        let body = if head.to_ascii_lowercase().contains("transfer-encoding: chunked") {
            dechunk(rest)?
        } else {
            rest.to_string()
        };

        if !(200..300).contains(&status) {
            return Err(format!("relay returned HTTP {status}: {}", body.trim().chars().take(300).collect::<String>()));
        }
        Ok(body)
    }
}

fn dechunk(mut s: &str) -> Result<String, String> {
    let mut out = String::new();
    loop {
        let (size_line, rest) = s.split_once("\r\n").ok_or("truncated chunk header")?;
        let n = usize::from_str_radix(size_line.trim().split(';').next().unwrap_or("0"), 16)
            .map_err(|_| "bad chunk size")?;
        if n == 0 {
            return Ok(out);
        }
        if rest.len() < n {
            return Err("truncated chunk body".into());
        }
        out.push_str(&rest[..n]);
        s = rest.get(n + 2..).ok_or("truncated chunk terminator")?;
    }
}
