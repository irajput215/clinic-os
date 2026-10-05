// Test users are created through the public signup endpoint. The development-only
// `POST /api/v1/private/users/` route no longer exists: it created users without
// authenticating the caller, and it was live on the deployed environment.
import { UsersService } from "../../src/client"
import { client } from "../../src/client/client.gen"

client.setConfig({
  baseURL: `${process.env.VITE_API_URL}`,
})

export const createUser = async ({
  email,
  password,
}: {
  email: string
  password: string
}) => {
  const response = await UsersService.registerUser({
    body: {
      email,
      password,
      full_name: "Test User",
    },
  })
  return response.data
}

/**
 * Register an organisation and its administrator, through the same public signup.
 *
 * The patients API resolves the tenant from the session and from nowhere else (INV-1), and
 * an account created without a `clinic_name` has no organisation: every patients call from
 * it is refused with `403`. A patients spec therefore has to register a clinic, not just an
 * account.
 */
export const createUserWithClinic = async ({
  email,
  password,
  clinicName,
}: {
  email: string
  password: string
  clinicName: string
}) => {
  const response = await UsersService.registerUser({
    body: {
      email,
      password,
      full_name: "Test User",
      clinic_name: clinicName,
    },
  })
  return response.data
}
