package com.cubeon.client.chat;

import java.util.List;
import java.util.Objects;
import java.util.function.Predicate;

/** One consecutive displayed run; original messages remain in vanilla history. */
public final class ChatStack {
    private static final int MAX_GAP_TICKS = 200;
    private Object content, source, indicator, connection, head;
    private int tick, count;

    public int accept(Object content, Object source, Object indicator, int tick,
                      Object connection, Object visibleHead) {
        long gap = (long) tick - this.tick;
        boolean repeated = count > 0 && head != null && head == visibleHead
                && this.connection == connection && gap >= 0 && gap <= MAX_GAP_TICKS
                && Objects.equals(this.content, content)
                && Objects.equals(this.source, source)
                && Objects.equals(this.indicator, indicator);
        count = repeated ? (count == Integer.MAX_VALUE ? count : count + 1) : 1;
        this.content = content;
        this.source = source;
        this.indicator = indicator;
        this.connection = connection;
        this.tick = tick;
        return count;
    }

    public void rememberHead(Object head) {
        this.head = head;
    }

    public void reset() {
        content = source = indicator = connection = head = null;
        count = tick = 0;
    }

    /** Native queues have the final wrapped line first; remove exactly one entry. */
    public static <T> int removeLatest(List<T> lines, Predicate<T> endOfEntry) {
        if (lines.isEmpty()) return 0;
        int length = 1;
        while (length < lines.size() && !endOfEntry.test(lines.get(length))) length++;
        lines.subList(0, length).clear();
        return length;
    }
}
