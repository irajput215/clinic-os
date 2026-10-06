import { z } from "@/lib/zod"

/** The API's own bounds for a password (`UserRegister`, `NewPassword`): 8 to 128 characters. */
export const PASSWORD_MIN = 8
export const PASSWORD_MAX = 128

export const PASSWORD_HINT = `At least ${PASSWORD_MIN} characters.`

export const newPassword = z
  .string()
  .min(1, "Choose a password.")
  .min(PASSWORD_MIN, `Use at least ${PASSWORD_MIN} characters.`)
  .max(PASSWORD_MAX, `Use ${PASSWORD_MAX} characters or fewer.`)

export const confirmPassword = z.string().min(1, "Enter the password again.")

export const PASSWORDS_DIFFER = "The passwords don't match."
