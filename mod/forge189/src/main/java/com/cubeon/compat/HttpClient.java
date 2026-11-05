package com.cubeon.compat;

import java.io.*;
import java.net.*;
import java.nio.charset.Charset;
import java.time.Duration;
import java.util.Map;

/** Bounded loopback-only transport; launcher capability headers never follow redirects. */
public final class HttpClient {
    public enum Redirect { NEVER }
    private final int connectTimeout;
    private HttpClient(int connectTimeout) { this.connectTimeout = connectTimeout; }
    public static Builder newBuilder() { return new Builder(); }
    public static final class Builder {
        private int timeout = 900;
        public Builder connectTimeout(Duration value) { timeout = milliseconds(value); return this; }
        public Builder followRedirects(Redirect value) { return this; }
        public HttpClient build() { return new HttpClient(timeout); }
    }
    private static int milliseconds(Duration value) {
        return (int)Math.max(1, Math.min(Integer.MAX_VALUE, value.toMillis()));
    }
    public HttpResponse<String> send(HttpRequest request, Charset charset) throws IOException, InterruptedException {
        if (Thread.currentThread().isInterrupted()) throw new InterruptedException();
        URI uri = request.uri;
        if (!"http".equals(uri.getScheme()) || !"127.0.0.1".equals(uri.getHost()) || uri.getUserInfo() != null)
            throw new IOException("Cubeon bridge endpoint must be loopback");
        HttpURLConnection connection = (HttpURLConnection)uri.toURL().openConnection(Proxy.NO_PROXY);
        connection.setConnectTimeout(connectTimeout);
        connection.setReadTimeout(milliseconds(request.timeout));
        connection.setInstanceFollowRedirects(false);
        for (Map.Entry<String, String> entry : request.headers.entrySet())
            connection.setRequestProperty(entry.getKey(), entry.getValue());
        try {
            if (request.body != null) {
                connection.setRequestMethod("POST");
                connection.setDoOutput(true);
                connection.setFixedLengthStreamingMode(request.body.length);
                try (OutputStream out = connection.getOutputStream()) { out.write(request.body); }
            }
            int code = connection.getResponseCode();
            InputStream stream = code >= 400 ? connection.getErrorStream() : connection.getInputStream();
            ByteArrayOutputStream bytes = new ByteArrayOutputStream();
            if (stream != null) try (InputStream in = stream) {
                byte[] block = new byte[8192];
                int count;
                while ((count = in.read(block)) != -1) {
                    if (bytes.size() + count > 4 * 1024 * 1024) throw new IOException("Cubeon bridge response too large");
                    bytes.write(block, 0, count);
                }
            }
            return new HttpResponse<String>(code, new String(bytes.toByteArray(), charset));
        } finally { connection.disconnect(); }
    }
}
