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
