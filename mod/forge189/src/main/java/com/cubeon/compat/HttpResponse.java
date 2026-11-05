package com.cubeon.compat;

import java.nio.charset.Charset;

public final class HttpResponse<T> {
    private final int status;
    private final T body;
    HttpResponse(int status, T body) { this.status = status; this.body = body; }
    public int statusCode() { return status; }
    public T body() { return body; }
    public static final class BodyHandlers {
        public static Charset ofString(Charset charset) { return charset; }
    }
}
