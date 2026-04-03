export function validatePassword(password: string): string[] {
  const errors: string[] = []
  if (password.length < 8) {
    errors.push('Пароль должен содержать минимум 8 символов')
  }
  if (!/[A-Z]/.test(password)) {
    errors.push('Пароль должен содержать хотя бы одну заглавную букву (A-Z)')
  }
  if (!/[a-z]/.test(password)) {
    errors.push('Пароль должен содержать хотя бы одну строчную букву (a-z)')
  }
  if (!/[0-9]/.test(password)) {
    errors.push('Пароль должен содержать хотя бы одну цифру (0-9)')
  }
  return errors
}
