//! Fabric CameraBlur's time-based 8 ms exposure, independent of render FPS.
#[derive(Default)]
pub struct CameraBlur {
    previous: Option<(f64, f64, f64, f64, u64)>,
    motion_time: f64,
    velocity: [f64; 2],
    vector: [f32; 2],
}
impl CameraBlur {
    pub fn reset(&mut self) {
        *self = Self::default();
    }
    #[allow(clippy::too_many_arguments)]
    pub fn update(
        &mut self,
        now: f64,
        yaw: f64,
        pitch: f64,
        fov: f64,
        aspect: f64,
        scene: u64,
        enabled: bool,
        intensity: f64,
    ) -> Option<[f32; 2]> {
        let intensity = if intensity.is_finite() {
            intensity.clamp(0., 1.)
        } else {
            1.
        };
        if !enabled
            || intensity <= 0.
            || ![now, yaw, pitch, fov, aspect].iter().all(|v| v.is_finite())
            || aspect <= 0.
        {
            self.reset();
            return None;
        }
        let Some((prev, y, p, f, s)) = self.previous.replace((now, yaw, pitch, fov, scene)) else {
            self.motion_time = now;
            return None;
        };
        let dt = now - prev;
        let mut sample_dt = now - self.motion_time;
        let turn = (yaw - y + 180.).rem_euclid(360.) - 180.;
        let tilt = pitch - p;
        if s != scene
            || dt <= 0.
            || dt > 0.15
            || turn.abs() / sample_dt > 6000.
            || tilt.abs() / sample_dt > 6000.
            || (fov - f).abs() / dt > 1200.
        {
            self.motion_time = now;
            self.velocity = [0.; 2];
            self.vector = [0.; 2];
            return None;
        }
        if turn.abs() + tilt.abs() < 1e-7 {
            if sample_dt >= 0.012 {
                self.velocity = [0.; 2];
                self.vector = [0.; 2];
            }
        } else {
            self.motion_time = now;
            if self.velocity == [0.; 2] && sample_dt > 0.012 {
                sample_dt = dt;
            }
            let scale = 2. * (fov.clamp(10., 170.).to_radians() / 2.).tan();
            let velocity = [
                turn.to_radians() / (sample_dt * scale * aspect),
                -tilt.to_radians() / (sample_dt * scale),
            ];
            let weight = -(-sample_dt / 0.024).exp_m1();
            for (v, next) in self.velocity.iter_mut().zip(velocity) {
                *v += (next - *v) * weight;
            }
            let exposure = self.velocity.map(|v| v * 0.008 * intensity);
            let length = exposure[0].hypot(exposure[1]);
            let limit = if length > 0.06 * intensity {
                0.06 * intensity / length
            } else {
                1.
            };
            self.vector = exposure.map(|v| (v * limit) as f32);
        }
        (self.vector[0] * self.vector[0] + self.vector[1] * self.vector[1] > 2.5e-9)
            .then_some(self.vector)
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn exposure_matches_across_fps_and_mouse_rates() {
        let expected =
            90f64.to_radians() * 0.008 / (2. * (70f64.to_radians() / 2.).tan() * 16. / 9.);
        for fps in [30, 60, 144, 240, 1000, 2000] {
            for hz in [125, 1000] {
                let mut blur = CameraBlur::default();
                let mut sum = 0.;
                let mut count = 0;
                for i in 0..=fps * 2 {
                    let t = i as f64 / fps as f64;
                    let input = (t * hz as f64 + 1e-8).floor() / hz as f64;
                    let vector =
                        blur.update(1. + t, 90. * input, 20. * input, 70., 16. / 9., 1, true, 1.);
                    if t > 0.5 {
                        let v = vector.expect("polled camera must not flicker sharp");
                        assert!((v[0] as f64 - expected).abs() < expected * 0.3);
                        sum += v[0] as f64;
                        count += 1;
                    }
                }
                assert!((sum / count as f64 - expected).abs() < expected * 0.025);
                assert!(
                    blur.update(3.02, 180., 40., 70., 16. / 9., 1, true, 1.)
                        .is_none()
                );
                assert!(
                    blur.update(3.03, 180., 40., 70., 16. / 9., 1, false, 1.)
                        .is_none()
                );
            }
        }
    }
    #[test]
    fn cuts_and_zero_intensity_reset() {
        let mut b = CameraBlur::default();
        b.update(1., 0., 0., 70., 1., 1, true, 1.);
        assert!(b.update(1.01, 90., 0., 70., 1., 1, true, 1.).is_none());
        assert!(b.update(1.02, 91., 0., 70., 1., 2, true, 1.).is_none());
        assert!(b.update(1.03, 92., 0., 70., 1., 2, true, 0.).is_none());
    }
}
