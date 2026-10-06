import { LoginService, UsersService } from "@/client"

/**
 * The signed-out account flows: registering an organisation and recovering a password. Each is one
 * API call; the server decides everything (open registration, rate limits, token validity).
 */

export interface OrganisationSignup {
  clinic_name: string
  full_name: string
  email: string
  password: string
}

/**
 * `POST /users/signup` with a `clinic_name`: one transaction creates the organisation, the account
 * and its Practice Owner grant. The tenant is created by the server; nothing here names one.
 */
export const registerOrganisation = async (body: OrganisationSignup) => {
  await UsersService.registerUser({ body })
}

/**
 * `POST /password-recovery/{email}`. The server answers the same way whether or not the address
 * has an account, so the caller can only ever say "if it's registered, a link is on its way".
 */
export const requestPasswordRecovery = async (email: string) => {
  await LoginService.recoverPassword({ path: { email } })
}

/** `POST /reset-password/`: spends the emailed token to set a new password. */
export const resetPassword = async (token: string, newPassword: string) => {
  await LoginService.resetPassword({
    body: { token, new_password: newPassword },
  })
}
