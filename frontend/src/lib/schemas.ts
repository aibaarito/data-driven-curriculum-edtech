import { z } from "zod";

export const MAX_UPLOAD_MB = 10;

export const uploadSchema = z.object({
  file: z
    .instanceof(File, { message: "Выберите файл." })
    .refine((f) => /\.(csv|xlsx)$/i.test(f.name), "Поддерживаются только файлы .csv и .xlsx.")
    .refine((f) => f.size > 0, "Файл пустой.")
    .refine((f) => f.size <= MAX_UPLOAD_MB * 1024 * 1024, `Размер файла не должен превышать ${MAX_UPLOAD_MB} МБ.`),
});
export type UploadForm = z.infer<typeof uploadSchema>;

export const settingsSchema = z
  .object({
    difficult_threshold: z.number({ message: "Введите число" }).min(0).max(100),
    watch_threshold: z.number({ message: "Введите число" }).min(0).max(100),
    target_mastery: z.number({ message: "Введите число" }).min(0).max(100),
    min_students_topic: z.number({ message: "Введите число" }).int("Целое число").min(1).max(10000),
    min_students_textbook: z.number({ message: "Введите число" }).int("Целое число").min(2).max(100000),
    min_classes_textbook: z.number({ message: "Введите число" }).int("Целое число").min(1).max(1000),
    max_change_pct: z.number({ message: "Введите число" }).min(0).max(100),
  })
  .refine((s) => s.difficult_threshold <= s.watch_threshold, {
    message: "Порог «трудная» не может быть выше порога «внимание».",
    path: ["difficult_threshold"],
  });
export type SettingsForm = z.infer<typeof settingsSchema>;

export const topicConstraintSchema = z
  .object({
    min_hours: z.number().min(0).max(1000),
    max_hours: z.number().min(0).max(1000),
    priority: z.number().int().min(1).max(3),
  })
  .refine((v) => v.min_hours <= v.max_hours, { message: "Минимум больше максимума", path: ["min_hours"] });

export const totalHoursSchema = z
  .number({ message: "Введите число" })
  .positive("Должно быть больше нуля")
  .max(10000)
  .refine((v) => Number.isInteger(v * 2), "Кратно 0,5 ч");
